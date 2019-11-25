# -*- coding: utf-8 -*-

from __future__ import absolute_import
import os

import pytest

from gaas_sample import *  # pylint: disable=unused-wildcard-import


def test_duplicate_exclude_bands(create_gaas_calc, assert_state):
    from aiida.engine import run_get_node
    from aiida.plugins import DataFactory
    from aiida.common import OutputParsingError
    # from aiida.common import calc_states
    builder = create_gaas_calc(
        projections_dict={
            'kind_name': 'As',
            'ang_mtm_name': 's'
        }
    )
    builder.parameters = DataFactory('dict')(
        dict=dict(
            num_wann=1,
            num_iter=12,
            wvfn_formatted=True,
            exclude_bands=[1] * 2 + [2, 3]
        )
    )
    _, node = run_get_node(builder)
    assert node.exit_status == 400


def test_mixed_case_settings_key(create_gaas_calc, configure_with_daemon):
    from aiida.engine import run
    from aiida.plugins import DataFactory
    from aiida.common import InputValidationError

    builder = create_gaas_calc()
    builder.settings = DataFactory('dict')(dict=dict(PostpROc_SeTup=True))
    with pytest.raises(InputValidationError):
        run(builder)
