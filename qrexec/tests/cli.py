#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
# Copyright (C) 2020 Paweł Marczewski <pawel@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

from unittest import mock
from pathlib import PosixPath

import asynctest
import pytest

from ..exc import AccessDenied
from ..tools import qrexec_policy_exec

# Disable warnings that conflict with Pytest's use of fixtures.
# pylint: disable=redefined-outer-name


class TestPolicy:
    def __init__(self):
        self.resolution_type = None
        self.targets_for_ask = None
        self.default_target = None
        self.target = None
        self.rule = mock.NonCallableMock()
        self.rule.filepath = 'file'
        self.rulelineno = 42

    def set_ask(self, targets_for_ask, default_target=None, notify=False):
        self.resolution_type = 'ask'
        self.targets_for_ask = targets_for_ask
        self.default_target = default_target
        self.rule.action.notify = notify

    def set_allow(self, target, notify=False):
        self.resolution_type = 'allow'
        self.target = target
        self.rule.action.notify = notify

    def set_deny(self, notify=True):
        self.resolution_type = 'deny'
        self.rule.action.notify = notify

    def evaluate(self, request):
        assert self.resolution_type is not None

        if self.resolution_type == 'ask':
            return request.ask_resolution_type(
                self.rule, request, user='user',
                targets_for_ask=self.targets_for_ask,
                default_target=self.default_target)

        if self.resolution_type == 'allow':
            return request.allow_resolution_type(
                self.rule, request, user='user', target=self.target)

        if self.resolution_type == 'deny':
            raise AccessDenied('denied', notify=self.rule.action.notify)

        assert False, self.resolution_type
        return None


@pytest.fixture(autouse=True)
def policy():
    """
    Mock for FilePolicy object that will evaluate the requests.
    """

    policy = TestPolicy()
    with mock.patch('qrexec.policy.parser.FilePolicy') as mock_policy:
        mock_policy.return_value = policy
        yield policy

    assert mock_policy.mock_calls == [
        mock.call(policy_path=PosixPath('/etc/qubes/policy.d'))
    ]


@pytest.fixture(autouse=True)
def system_info():
    system_info = {
        'domains': {
            'dom0': {'icon': 'black', 'template_for_dispvms': False,
                     'guivm': None},
            'source': {'icon': 'red', 'template_for_dispvms': False,
                       'guivm': 'gui'},
            'test-vm1': {'icon': 'red', 'template_for_dispvms': False,
                         'guivm': None},
            'test-vm2': {'icon': 'red', 'template_for_dispvms': False,
                         'guivm': None},
            'test-vm3': {'icon': 'green', 'template_for_dispvms': True,
                         'guivm': None},
            'gui': {'icon': 'orange', 'template_for_dispvms': False,
                    'guivm': None},
        }
    }
    with mock.patch('qrexec.utils.get_system_info') as mock_system_info:
        mock_system_info.return_value = system_info
        yield system_info


@pytest.fixture
def icons():
    return {
        'dom0': 'black',
        'source': 'red',
        'test-vm1': 'red',
        'test-vm2': 'red',
        'test-vm3': 'green',
        '@dispvm:test-vm3': 'green',
        'gui': 'orange',
    }


@pytest.fixture(autouse=True)
def execute():
    """
    Mock for execute() for allowed action. It is supposed to call the qrexec.
    """

    with mock.patch('qrexec.policy.parser.AllowResolution.execute',
                    asynctest.CoroutineMock()) as mock_execute:
        yield mock_execute


@pytest.fixture(autouse=True)
def agent_service():
    """
    Mock for call_socket_service() used to contact the qrexec-policy-agent.
    """

    with mock.patch('qrexec.tools.qrexec_policy_exec.call_socket_service',
                    asynctest.CoroutineMock()) as mock_call_socket_service:
        yield mock_call_socket_service


def test_000_allow(policy, execute, agent_service):
    policy.set_allow('test-vm1')
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service+arg', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == []
    assert execute.mock_calls == [
        mock.call('process_ident,source,source-id'),
    ]


def test_001_allow_notify(policy, execute, agent_service):
    policy.set_allow('test-vm1', notify=True)
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service+arg', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Notify', 'dom0', {
            'resolution': 'allow',
            'service': 'service',
            'source': 'source',
            'target': 'test-vm1',
        })
    ]
    assert execute.mock_calls == [
        mock.call('process_ident,source,source-id'),
    ]


def test_002_allow_notify_failed(policy, execute, agent_service):
    policy.set_allow('test-vm1', notify=True)
    agent_service.side_effect = Exception("calling agent service failed")

    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service+arg', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Notify', 'dom0', {
            'resolution': 'allow',
            'service': 'service',
            'source': 'source',
            'target': 'test-vm1',
        })
    ]
    assert execute.mock_calls == [
        mock.call('process_ident,source,source-id'),
    ]


def test_010_ask_allow(icons, policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'])
    agent_service.return_value = 'test-vm1'
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service+arg', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Ask', 'dom0', {
            'source': 'source',
            'service': 'service',
            'targets': ['test-vm1', 'test-vm2'],
            'default_target': '',
            'icons': icons,
        }),
    ]
    assert execute.mock_calls == [
        mock.call('process_ident,source,source-id'),
    ]


def test_011_ask_allow_notify(icons, policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'], notify=True)
    agent_service.return_value = 'test-vm1'
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service+arg', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Ask', 'dom0', {
            'source': 'source',
            'service': 'service',
            'targets': ['test-vm1', 'test-vm2'],
            'default_target': '',
            'icons': icons,
        }),
        mock.call('gui', 'policy.Notify', 'dom0', {
            'resolution': 'allow',
            'service': 'service',
            'source': 'source',
            'target': 'test-vm1',
        }),
    ]
    assert execute.mock_calls == [
        mock.call('process_ident,source,source-id'),
    ]


def test_015_ask_deny(icons, policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'])
    agent_service.return_value = ''
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Ask', 'dom0', {
            'source': 'source',
            'service': 'service',
            'targets': ['test-vm1', 'test-vm2'],
            'default_target': '',
            'icons': icons,
        }),
    ]
    assert execute.mock_calls == []


def test_016_ask_deny_notify(icons, policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'], notify=True)
    agent_service.return_value = ''
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Ask', 'dom0', {
            'source': 'source',
            'service': 'service',
            'targets': ['test-vm1', 'test-vm2'],
            'default_target': '',
            'icons': icons,
        }),
        mock.call('gui', 'policy.Notify', 'dom0', {
            'resolution': 'deny',
            'service': 'service',
            'source': 'source',
            'target': 'test-vm1',
        }),
    ]
    assert execute.mock_calls == []


def test_017_ask_default_target(icons, policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'], 'test-vm1')
    agent_service.return_value = 'test-vm1'
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Ask', 'dom0', {
            'source': 'source',
            'service': 'service',
            'targets': ['test-vm1', 'test-vm2'],
            'default_target': 'test-vm1',
            'icons': icons,
        }),
    ]
    assert execute.mock_calls == [
        mock.call('process_ident,source,source-id'),
    ]


def test_013_ask_no_guivm(policy, system_info, agent_service, execute):
    system_info['domains']['source']['guivm'] = None
    policy.set_ask(['test-vm1', 'test-vm2'])
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == []
    assert execute.mock_calls == []


def test_020_deny(policy, agent_service, execute):
    policy.set_deny()
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == [
        mock.call('gui', 'policy.Notify', 'dom0', {
            'resolution': 'deny',
            'service': 'service',
            'source': 'source',
            'target': 'test-vm1',
        }),
    ]
    assert execute.mock_calls == []


def test_021_deny_no_notify(policy, agent_service, execute):
    policy.set_deny(notify=False)
    retval = qrexec_policy_exec.main(
        ['source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == []
    assert execute.mock_calls == []


def test_030_just_evaluate_allow(policy, agent_service, execute):
    policy.set_allow('test-vm1')
    retval = qrexec_policy_exec.main(
        ['--just-evaluate',
         'source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == []
    assert execute.mock_calls == []


def test_031_just_evaluate_deny(policy, agent_service, execute):
    policy.set_deny()
    retval = qrexec_policy_exec.main(
        ['--just-evaluate',
         'source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == []
    assert execute.mock_calls == []


def test_032_just_evaluate_ask(policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'])
    retval = qrexec_policy_exec.main(
        ['--just-evaluate',
         'source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 1
    assert agent_service.mock_calls == []
    assert execute.mock_calls == []


def test_033_just_evaluate_ask_assume_yes(policy, agent_service, execute):
    policy.set_ask(['test-vm1', 'test-vm2'])
    retval = qrexec_policy_exec.main(
        ['--just-evaluate', '--assume-yes-for-ask',
         'source-id', 'source', 'test-vm1', 'service', 'process_ident'])
    assert retval == 0
    assert agent_service.mock_calls == []
    assert execute.mock_calls == []
