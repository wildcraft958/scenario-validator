"""Phase-3 protocol-correctness tests (TDD red-first): per-scenario speed/decel checks.

Grounds three check fixes against the EuroNCAP protocol + the scenario filename grammar:
  SC_18 - also verifies the TARGET speed (not just the VUT): the .xosc target trajectory/
          init speed must match the designed speed encoded in the filename target token
          (e.g. '5EPTa', '45GVT'); a disagreement is a likely naming/authoring mistake.
  SC_15 - a target DESIGNED to move (filename token speed > 0) is a moving actor, even
          when it is parametric (no FollowTrajectoryAction) - it must not be force-checked
          for 0 m/s. Stationary-vs-moving is gated by the design, not just the name.
  MR_02 - the -4 m/s2 braking rate applies only to genuine DECELERATIONS (target speed 0,
          or target < current). An ACCELERATING target (CPLA/CBLA) is not a braking action
          and must be NA, not FAIL.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from lxml import etree  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
CPTA_XOSC = EXAMPLES / "CPTA" / "AEB_CPTAno_10VUT_5EPTa_10Imp.xosc"

_PARSER = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)


def _parse(xml: bytes):
    return etree.parse(io.BytesIO(xml), _PARSER).getroot()


@pytest.fixture(scope="module")
def config():
    from src.models import Config
    return Config.load(ROOT / "config.json")


# ============================================================
# CH_SC_18: target speed must match the filename target token
# ============================================================

class TestSC18TargetSpeed:
    def test_real_cpta_target_speed_passes(self, config):
        """Real CPTA EPTa moves ~5.1 km/h, filename token is 5EPTa -> agree -> PASS."""
        if not CPTA_XOSC.exists():
            pytest.skip("CPTA example not present")
        from src.parsers import xosc as xp
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_18
        root = xp.load(CPTA_XOSC)
        pn = parse_scenario_filename("AEB_CPTAno_10VUT_5EPTa_10Imp", config)
        result = check_sc_18(root, config, scenario_tag="CPTA", parsed_name=pn)
        assert result.status == "PASS", result.comment

    def test_target_speed_mismatch_flags(self, config):
        """Filename lies: 50EPTa while the real EPTa moves ~5 km/h -> MANUAL_REVIEW."""
        if not CPTA_XOSC.exists():
            pytest.skip("CPTA example not present")
        from src.parsers import xosc as xp
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_18
        root = xp.load(CPTA_XOSC)
        pn = parse_scenario_filename("AEB_CPTAno_10VUT_50EPTa_10Imp", config)
        result = check_sc_18(root, config, scenario_tag="CPTA", parsed_name=pn)
        assert result.status == "MANUAL_REVIEW", result.comment
        assert "target" in result.comment.lower()

    def test_lower_boundary_speed_passes_via_design_token(self, config):
        """A 10 km/h VUT design whose measured speed reads 9.98 km/h (vertex discretisation) must
        PASS the [10, 25] CCFtap range. The exact filename token (10VUT) is graded, not the noisy
        measurement - the boundary bug was a strict 9.98 < 10 compare that false-FAILed a valid
        band-edge speed."""
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_18
        xosc = (
            b'<?xml version="1.0"?><OpenSCENARIO><FileHeader description="sc18"/>'
            b'<Entities><ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>'
            b'<ScenarioObject name="GVT"><Vehicle name="GVT"/></ScenarioObject></Entities>'
            b'<Storyboard><Init><Actions><Private entityRef="VUT"><PrivateAction>'
            b'<LongitudinalAction><SpeedAction>'
            b'<SpeedActionDynamics dynamicsDimension="time" dynamicsShape="step" value="0"/>'
            b'<SpeedActionTarget><AbsoluteTargetSpeed value="2.772"/></SpeedActionTarget>'  # 9.98 km/h
            b'</SpeedAction></LongitudinalAction></PrivateAction></Private>'
            b'</Actions></Init><StopTrigger/></Storyboard></OpenSCENARIO>'
        )
        root = _parse(xosc)
        pn = parse_scenario_filename("AEB_CCFtap_10VUT_30GVT_50Imp", config)
        result = check_sc_18(root, config, scenario_tag="CCFtap", parsed_name=pn)
        assert result.status == "PASS", result.comment


# ============================================================
# CH_SC_15: a designed-moving target (token > 0) is not a stationary target
# ============================================================

def _moving_parametric_xosc(name: str, init_ms: float) -> bytes:
    """A target with an Init speed > 0 but NO FollowTrajectoryAction (parametric)."""
    return f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader description="phase3"/>
  <Entities>
    <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
    <ScenarioObject name="{name}"><Vehicle name="{name}"/></ScenarioObject>
  </Entities>
  <Storyboard>
    <Init><Actions>
      <Private entityRef="{name}">
        <PrivateAction><LongitudinalAction><SpeedAction>
          <SpeedActionDynamics dynamicsDimension="time" dynamicsShape="step" value="0"/>
          <SpeedActionTarget><AbsoluteTargetSpeed value="{init_ms}"/></SpeedActionTarget>
        </SpeedAction></LongitudinalAction></PrivateAction>
      </Private>
    </Actions></Init>
    <StopTrigger/>
  </Storyboard>
</OpenSCENARIO>""".encode()


class TestSC15DesignedMoving:
    def test_designed_moving_emt_not_flagged(self, config):
        """EMT designed to move at 30 km/h (filename token) but parametric (no trajectory).
        It is a moving actor -> NA, not a 0-speed FAIL."""
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_15
        root = _parse(_moving_parametric_xosc("EMT", 8.33))  # 8.33 m/s = 30 km/h
        pn = parse_scenario_filename("AEB_CMRb_30VUT_30EMT_50Imp", config)
        result = check_sc_15(root, config, parsed_name=pn)
        assert result.status != "FAIL", result.comment

    def test_stationary_target_with_speed_still_fails(self, config):
        """A target designed stationary (no token speed) but with Init speed > 0 -> FAIL."""
        from src.checks.scenario import check_sc_15
        root = _parse(_moving_parametric_xosc("EMT", 8.33))
        result = check_sc_15(root, config, parsed_name=None)
        assert result.status == "FAIL", result.comment


# ============================================================
# CH_MR_02: -4 m/s2 applies only to genuine decelerations
# ============================================================

def _speed_action_xosc(name: str, init_ms: str, rate: str, target_ms: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenSCENARIO>
  <FileHeader description="phase3_mr02"/>
  <Entities>
    <ScenarioObject name="Ego"><Vehicle name="Ego"/></ScenarioObject>
    <ScenarioObject name="{name}"><Vehicle name="{name}"/></ScenarioObject>
  </Entities>
  <Storyboard>
    <Init><Actions>
      <Private entityRef="{name}">
        <PrivateAction><LongitudinalAction><SpeedAction>
          <SpeedActionDynamics dynamicsDimension="time" dynamicsShape="step" value="0"/>
          <SpeedActionTarget><AbsoluteTargetSpeed value="{init_ms}"/></SpeedActionTarget>
        </SpeedAction></LongitudinalAction></PrivateAction>
      </Private>
    </Actions></Init>
    <Story name="S">
      <Act name="Act">
        <ManeuverGroup name="MG" maximumExecutionCount="1">
          <Actors selectTriggeringEntities="false"><EntityRef entityRef="{name}"/></Actors>
          <Maneuver name="M"><Event name="E" priority="overwrite"><Action name="A">
            <PrivateAction><LongitudinalAction><SpeedAction>
              <SpeedActionDynamics dynamicsDimension="rate" dynamicsShape="linear" value="{rate}"/>
              <SpeedActionTarget><AbsoluteTargetSpeed value="{target_ms}"/></SpeedActionTarget>
            </SpeedAction></LongitudinalAction></PrivateAction>
          </Action><StartTrigger/></Event></Maneuver>
        </ManeuverGroup>
        <StartTrigger/>
      </Act>
    </Story>
    <StopTrigger/>
  </Storyboard>
</OpenSCENARIO>""".encode()


class TestMR02DecelApplicability:
    def test_acceleration_action_is_na(self, config):
        """Target accelerates 4 -> 8 m/s (CPLA/CBLA style) -> not a braking action -> NA."""
        from src.checks.model_review import check_mr_02
        root = _parse(_speed_action_xosc("EBTa", "4.0", "2.0", "8.0"))
        result = check_mr_02(root, config)
        assert result.status == "NA", result.comment

    def test_decel_to_nonzero_at_4_passes(self, config):
        """Target brakes 20 -> 10 m/s at 4 m/s2 -> genuine deceleration -> PASS."""
        from src.checks.model_review import check_mr_02
        root = _parse(_speed_action_xosc("GVT", "20.0", "4.0", "10.0"))
        result = check_mr_02(root, config)
        assert result.status == "PASS", result.comment

    def test_brake_to_stop_wrong_rate_still_fails(self, config):
        """Braking to a full stop at 2 m/s2 (wrong) -> FAIL (decel applicability unchanged)."""
        from src.checks.model_review import check_mr_02
        root = _parse(_speed_action_xosc("GVT", "13.89", "2.0", "0"))
        result = check_mr_02(root, config)
        assert result.status == "FAIL", result.comment

    def test_signed_decel_rate_passes(self, config):
        """Some authoring tools export a signed -4.0 for a 4 m/s2 deceleration. The magnitude
        matches the protocol rate, so it must PASS, not false-fail on abs(-4 - 4) = 8."""
        from src.checks.model_review import check_mr_02
        root = _parse(_speed_action_xosc("GVT", "20.0", "-4.0", "10.0"))
        result = check_mr_02(root, config)
        assert result.status == "PASS", result.comment
