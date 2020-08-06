# Copyright (c) 2020 SUSE LINUX GmbH
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

import logging
import os
import pytest

logger = logging.getLogger(__name__)


# check if all default services are available
def test_services(rook_cluster):
    services = ["csi-cephfsplugin-metrics",
                "csi-rbdplugin-metrics",
                "rook-ceph-mgr",
                "rook-ceph-mgr-dashboard",
                "rook-ceph-mon-a",
                "rook-ceph-mon-b",
                "rook-ceph-mon-c"]

    for service in services:
        found = rook_cluster.kubernetes.wait_for_service(service)
        if found is False:
            pytest.fail("Could not find service %s", service)


# check if rbd service gets started automatically
def test_service_rbd(rook_cluster):
    # create an ObjectStore
    output = rook_cluster.kubernetes.kubectl_apply(
                os.path.join(rook_cluster.ceph_dir, 'object-test.yaml'))

    if output[0] != 0:
        pytest.fail("Could not create an ObjectStore")

    found = rook_cluster.kubernetes.wait_for_service("rook-ceph-rgw-my-store",
                                                     iteration=20)

    if found is False:
        pytest.fail("rgw service has not been started automatically")