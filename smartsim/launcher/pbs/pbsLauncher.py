import time
from ...error import SSUnsupportedError
from ..stepInfo import PBSStepInfo, UnmanagedStepInfo
from ..launcher import Launcher
from ..taskManager import TaskManager
from ...error import LauncherError, SSConfigError
from .pbsParser import parse_qstat_nodes
from .pbsParser import parse_qstat_jobid, parse_step_id_from_qstat
from .pbsCommands import qstat, qdel
from ..step import AprunStep, QsubBatchStep
from ...settings import AprunSettings, QsubBatchSettings
from ..stepMapping import StepMapping
from ...constants import STATUS_COMPLETED

from ...utils import get_logger
logger = get_logger(__name__)

class PBSLauncher(Launcher):
    """This class encapsulates the functionality needed
    to launch jobs on systems that use PBS as a workload manager.

    All WLM launchers are capable of launching managed and unmanaged
    jobs. Managed jobs are queried through interaction with with WLM,
    in this case PBS. Unmanaged jobs are held in the TaskManager
    and are managed through references to their launching process ID
    i.e. a psutil.Popen object
    """

    def __init__(self):
        """Initialize a PBSLauncher
        """
        super().__init__()
        self.task_manager = TaskManager()
        self.step_mapping  = StepMapping()


    def create_step(self, name, cwd, step_settings):
        """Create a PBSpro job step

        :param name: name of the entity to be launched
        :type name: str
        :param cwd: path to launch dir
        :type cwd: str
        :param step_settings: batch or run settings for entity
        :type step_settings: BatchSettings | RunSettings
        :raises SSUnsupportedError: if batch or run settings type isnt supported
        :raises LauncherError: if step creation fails
        :return: step instance
        :rtype: Step
        """
        try:
            if isinstance(step_settings, AprunSettings):
                step = AprunStep(name, cwd, step_settings)
                return step
            elif isinstance(step_settings, QsubBatchSettings):
                step = QsubBatchStep(name, cwd, step_settings)
                return step
            raise TypeError(
                f"RunSettings type {type(step_settings)} not supported by PBSPro")
        except SSConfigError as e:
            raise LauncherError("Job step creation failed: " + str(e)) from None

    def get_step_update(self, step_names):
        """Get update for a list of job steps

        :param step_names: list of job steps to get updates for
        :type step_names: list[str]
        :return: list of job updates
        :rtype: list[StepInfo]
        """
        updates = []

        # get updates of jobs managed by PBS (just qsub batch for now)
        step_ids = self.step_mapping.get_ids(step_names, managed=True)
        if len(step_ids) > 0:
            updates.extend(self._get_managed_step_update(step_ids))

        # get updates of unmanaged jobs (Aprun, mpirun, etc)
        task_ids = self.step_mapping.get_ids(step_names, managed=False)
        if len(task_ids) > 0:
            updates.extend(self._get_unmanaged_step_update(task_ids))

        for update in updates:
            logger.debug(update)
        return updates

    def get_step_nodes(self, step_name):
        """Return the compute nodes of a specific job or allocation

        This function returns the compute nodes of a specific job or allocation
        in a list with the duplicates removed.

        :param step_names: list of job step names
        :type step_names: list[str]
        :raises SSUnsupportedError: nodelist aquisition isn't supported on PBS
        """
        raise SSUnsupportedError("SmartSim does not support PBSPro node aquisition")

    def run(self, step):
        """Run a job step through PBSPro

        :param step: a job step instance
        :type step: Step
        :raises LauncherError: if launch fails
        :return: job step id if job is managed
        :rtype: str
        """
        if not self.task_manager.actively_monitoring:
            self.task_manager.start()

        cmd_list = step.get_launch_cmd()
        step_id = None
        task_id = None
        if isinstance(step, QsubBatchStep): # make this QsubBatchStep
            # wait for batch step to submit successfully
            rc, out, err = self.task_manager.start_and_wait(cmd_list, step.cwd)
            if rc != 0:
                raise LauncherError(f"Qsub batch submission failed\n {out}\n {err}")
            if out:
                step_id = out.strip()
                logger.debug(f"Gleaned batch job id: {step_id} for {step.name}")
        else:
            # aprun doesn't direct output for us.
            out, err = step.get_output_files()
            output = open(out, "w+")
            error = open(err, "w+")
            task_id = self.task_manager.start_task(cmd_list, step.cwd, out=output, err=error)

        # if batch submission did not successfully retrieve job ID
        if not step_id and step.managed:
            step_id = self._get_pbs_step_id(step)
        self.step_mapping.add(step.name, step_id, task_id, step.managed)
        return step_id

    def stop(self, step_name):
        """Step a job step

        :param step_name: name of the job to stop
        :type step_name: str
        :return: update for job due to cancel
        :rtype: StepInfo
        """
        stepmap = self.step_mapping[step_name]
        if stepmap.managed:
            qdel_rc, _, err = qdel([str(stepmap.step_id)])
            if qdel_rc != 0:
                logger.warning(f"Unable to cancel job step {step_name}\n {err}")
            if stepmap.task_id:
                self.task_manager.remove_task(stepmap.task_id)
        else:
            self.task_manager.remove_task(stepmap.task_id)

        step_info = self.get_step_update([step_name])[0]
        step_info.status = "Cancelled" # set status to cancelled instead of failed
        return step_info

    def _get_pbs_step_id(self, step, interval=2, trials=5):
        """Get the step_id of a step from qstat (rarely used)

        Parses qstat JSON output by looking for the step name
        """
        time.sleep(interval)
        step_id = "unassigned"
        while trials > 0:
            output, _ = qstat(
                ["-f", "-F", "json"]
            )
            step_id = parse_step_id_from_qstat(output, step.name)
            if step_id:
                break
            else:
                time.sleep(interval)
                trials -= 1
        if not step_id:
            raise LauncherError("Could not find id of launched job step")
        return step_id


    def _get_managed_step_update(self, step_ids):
        """Get step updates for WLM managed jobs

        :param step_ids: list of job step ids
        :type step_ids: list[str]
        :return: list of updates for managed jobs
        :rtype: list[StepInfo]
        """
        # TODO detect wether job history is available.
        qstat_out, _ = qstat(step_ids)

        stats = [parse_qstat_jobid(qstat_out, str(step_id)) for step_id in step_ids]
        # create PBSStepInfo objects to return
        updates = []
        for stat, step_id in zip(stats, step_ids):
            info = PBSStepInfo(stat, None)
            # account for case where job history is not logged by PBS
            if info.status == STATUS_COMPLETED:
                info.returncode = 0

            updates.append(info)
        return updates

    def _get_unmanaged_step_update(self, task_ids):
        """Get step updates for Popen managed jobs

        :param task_ids: task id to check
        :type task_ids: list[str]
        :return: list of step updates
        :rtype: list[StepInfo]
        """
        updates = []
        for task_id in task_ids:
            stat, rc, out, err = self.task_manager.get_task_update(task_id)
            update = UnmanagedStepInfo(stat, rc, out, err)
            updates.append(update)
        return updates

    def __str__(self):
        #TODO get the version here
        return "PBSPro"