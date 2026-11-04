import unittest
from unittest.mock import Mock, patch

from core.macos_spaces import SpaceController


class SpaceControllerTests(unittest.TestCase):
    def controller(self, current=32):
        controller = SpaceController.__new__(SpaceController)
        controller.sky = Mock()
        controller.connection = 1
        controller.sky.SLSGetActiveSpace.return_value = current
        controller.displays = Mock(return_value=[self.display(current)])
        controller._select = Mock()
        return controller

    def display(self, current):
        return {'Display Identifier': 'screen',
                'Current Space': {'ManagedSpaceID': current},
                'Spaces': [{'ManagedSpaceID': sid} for sid in [1, 32, 27]]}

    def test_boundary_does_not_modify_visibility(self):
        controller = self.controller(1)
        self.assertEqual(controller.switch(-1), (1, 1))
        controller._select.assert_not_called()

    def test_transition_requires_target_in_live_snapshot(self):
        controller = self.controller()
        controller.displays.side_effect = [[self.display(32)], [self.display(27)]]
        controller.sky.SLSGetActiveSpace.side_effect = [32, 27]
        self.assertEqual(controller.switch(1), (32, 27))
        controller._select.assert_called_once_with('screen', 32, 27)

    def test_unchanged_space_rolls_back_and_fails(self):
        controller = self.controller()
        with patch('core.macos_spaces.time.monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, 'dogrulamadi'):
                controller.switch(1)
        self.assertEqual(controller._select.call_count, 2)
        controller._select.assert_called_with('screen', 27, 32)
