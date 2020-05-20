# Copyright (c) 2019 SUSE LINUX GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# The Hardware module should take care of the operating system abstraction
# through images.
# libcloud will provide a common set of cloud-agnostic objects such as Node[s]
# We might extend the Node object to have an easy way to run arbitrary commands
# on the node such as Node.execute().
# There will be a challenge where those arbitrary commands differ between OS's;
# this is an abstraction that is not yet well figured out, but will likely
# take the form of cloud-init or similar bringing the target node to an
# expected state.

from abc import ABC, abstractmethod
import logging
import os
from pprint import pformat
import subprocess
from typing import Dict, Optional, Any

import paramiko.rsakey

from tests.lib.distro import get_distro
from tests.lib.ansible_helper import AnsibleRunner
from tests.lib.hardware.node_base import NodeBase, NodeRole

from tests.lib.workspace import Workspace

logger = logging.getLogger(__name__)


class HardwareBase(ABC):
    """
    Base Hardware class
    """
    def __init__(self, workspace: Workspace):
        self._workspace = workspace
        self._nodes: Dict[str, NodeBase] = {}
        self._conn = self.get_connection()

        logger.info(f"hardware {self}: Using {self.workspace.name}")
        self._sshkey_name: Optional[str] = None
        self._public_key: Optional[str] = None
        self._private_key: Optional[str] = None

        self._ansible_runner: Optional[AnsibleRunner] = None
        self._ansible_runner_nodes: Dict[str, NodeBase] = {}

        self._generate_keys()

    @property
    def workspace(self):
        return self._workspace

    @property
    def conn(self):
        return self._conn

    @property
    def nodes(self):
        return self._nodes

    @property
    def sshkey_name(self):
        return self._sshkey_name

    @property
    def public_key(self):
        return self._public_key

    @property
    def private_key(self):
        return self._private_key

    def _generate_keys(self):
        """
        Generatees a public and private key
        """
        key = paramiko.rsakey.RSAKey.generate(2048)
        self._private_key = os.path.join(
            self.workspace.working_dir, 'private.key')
        with open(self._private_key, 'w') as key_file:
            key.write_private_key(key_file)
        os.chmod(self._private_key, 0o400)

        self._sshkey_name = "%s_key" % (self.workspace.name)
        self._public_key = "%s %s" % (key.get_name(), key.get_base64())

    def _node_remove_ssh_key(self, node: NodeBase):
        # The mitogen plugin does not correctly ignore host key checking, so we
        # should remove any host keys for our nodes before starting.
        # The 'ssh' connection imports ssh-keys for us, so as a first step we
        # run a standard ssh connection to do the imports. We could import the
        # sshkeys manually first, but we also want to wait on the connection to
        # be available (in order to even be able to get them).
        # Therefore simply remove any entries from your known_hosts. It's also
        # helpful to do this after a build to clean up anything locally.
        subprocess.run(f"ssh-keygen -R {node.get_ssh_ip()}", shell=True)

    def destroy(self):
        for n in list(self.nodes):
            self.node_remove(self.nodes[n])

    @abstractmethod
    def get_connection(self):
        pass

    def node_add(self, node: NodeBase):
        logger.info(f"adding new node {node.name} to hardware {self}")
        self._node_remove_ssh_key(node)
        self.nodes[node.name] = node

    def node_remove(self, node: NodeBase):
        logger.info(f"removing node {node.name} from hardware {self}")
        del self.nodes[node.name]
        node.destroy()

    @abstractmethod
    def boot_nodes(self, masters: int = 1, workers: int = 2, offset: int = 0):
        logger.info("boot nodes")

    def prepare_nodes(self):
        logger.info("prepare nodes")
        d = get_distro()()

        self.execute_ansible_play(d.wait_for_connection_play())
        self.execute_ansible_play(d.bootstrap_play())

    def execute_ansible_play_raw(self, playbook):
        if not self._ansible_runner or \
           self._ansible_runner_nodes != self.nodes:
            # Create a new AnsibleRunner if the nodes dict has changed (to
            # generate a new inventory).
            self._ansible_runner = AnsibleRunner(self.nodes, self.working_dir)
            self._ansible_runner_nodes = self.nodes.copy()

        return self._ansible_runner.run_play_raw(playbook)

    def _execute_ansible_play(self, play_source):
        if not self._ansible_runner or \
           self._ansible_runner_nodes != self.nodes:
            # Create a new AnsibleRunner if the nodes dict has changed (to
            # generate a new inventory).
            self._ansible_runner = AnsibleRunner(self.workspace, self)
            self._ansible_runner_nodes = self.nodes.copy()

        return self._ansible_runner.run_play(play_source)

    def execute_ansible_play(self, play_source):
        r = self._execute_ansible_play(play_source)
        failure = False
        if r.host_unreachable:
            logger.error("One or more hosts were unreachable")
            logger.error(pformat(r.host_unreachable))
            failure = True
        if r.host_failed:
            logger.error("One or more hosts failed")
            logger.error(pformat(r.host_failed))
            failure = True
        if failure:
            logger.debug("The successful hosts returned:")
            logger.debug(pformat(r.host_ok))
            raise Exception(
                f"Failure running ansible playbook {play_source['name']}")
        return r

    def ansible_inventory_vars(self) -> Dict[str, Any]:
        vars = {
            'ansible_ssh_private_key_file': self.private_key,
            'ansible_host_key_checking': False,
            'ansible_ssh_host_key_checking': False,
            'ansible_scp_extra_args': '-o StrictHostKeyChecking=no',
            'ansible_ssh_extra_args': '-o StrictHostKeyChecking=no',
            'ansible_python_interpreter': '/usr/bin/python3',
        }
        return vars

    def get_node_by_role(self, role: NodeRole):
        items = []
        for node_name, node_obj in self.nodes.items():
            if node_obj._role == role:
                items.append(node_obj)
        return items

    def get_masters(self):
        self.masters = self.get_node_by_role(NodeRole.MASTER)
        return self.masters

    def get_workers(self):
        self.workers = self.get_node_by_role(NodeRole.WORKER)
        return self.workers

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.destroy()
