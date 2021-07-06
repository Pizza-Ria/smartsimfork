# BSD 2-Clause License
#
# Copyright (c) 2021, Hewlett Packard Enterprise
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import json


def parse_bsub(output):
    """Parse bsub output and return job id.

    :param output: stdout of bsub command
    :type output: str
    :returns: job id
    :rtype: str
    """
    for line in output.split("\n"):
        if line.startswith("Job"):
            return line.split()[1][1:-1]


def parse_bsub_error(output):
    """Parse and return error output of a failed bsub command.

    :param output: stderr of qsub command
    :type output: str
    :returns: error message
    :rtype: str
    """
    # Search for first non-empty line
    output_lines = output.split("\n")
    for line_num, line in enumerate(output.split("\n")):
        if line.strip():
            error = "\n".join(output_lines[line_num:])
            return error.strip()
    
    # if no non-empty line was received,
    # present a base error message
    base_err = "LSF run error"
    return base_err


def parse_bjobs_jobid(output, job_id):
    """Parse and return output of the bjobs command run with options
    to obtain job status.

    :param output: output of the bjobs command
    :type output: str
    :param job_id: allocation id or job step id
    :type job_id: str
    :return: status
    :rtype: str
    """
    result = "NOTFOUND"
    for line in output.split("\n"):
        if line.strip().startswith(job_id):
            line = line.split()
            stat = line[2]
            result = stat
            break
    return result


def parse_bjobs_nodes(output):
    """Parse and return the bjobs command run with
    options to obtain node list.

    This function parses and returns the nodes of
    a job in a list with the duplicates removed.

    :param output: output of the `bjobs -w` command
    :type output: str
    :return: compute nodes of the allocation or job
    :rtype: list of str
    """
    nodes = []
    
    lines = output.split("\n")

    nodes_str = lines[1][5]
    nodes = nodes_str.split(':')[1:]

    return list(sorted(set(nodes)))


def parse_step_id_from_bjobs(output, step_name):
    """Parse and return the step id from a bjobs command

    :param output: output bjobs
    :type output: str
    :param step_name: the name of the step to query
    :type step_name: str
    :return: the step_id
    :rtype: str
    """
    step_id = None

    lines = output.split("\n")

    for line in output.split("\n"):
        fields = line.split(" ")
        if fields[6] == step_name:
            step_id = fields[0]

    return step_id
