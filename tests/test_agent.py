from cad_copilot.agent.agent import CadCopilot, extract_final
from cad_copilot.agent.router import heuristic_route
from cad_copilot.eval.generate_questions import build
from cad_copilot.eval.metrics import score
from cad_copilot.llm.client import LLMClient


def test_extract_final():
    assert extract_final("blah\nFINAL: 12.5") == "12.5"
    assert extract_final("NOT_FOUND: nope") == "NOT_FOUND"
    assert extract_final("no marker") is None


def test_router_examples():
    assert heuristic_route("How many doors are there?") == "compute"
    assert heuristic_route("What is the minimum corridor width in the spec?") == "spec"
    assert heuristic_route("Where is the kitchen?") == "visual"
    assert heuristic_route("Does the corridor meet the minimum width required by the spec?") == "compliance"
    assert heuristic_route("How many doors?", has_spec=False) == "compute"
    assert heuristic_route("How many doors?", has_drawing=False) == "spec"
    assert heuristic_route("Are all breakers correctly sized for their cables according to the spec?") == "compliance"
    assert heuristic_route("What is the total connected load of circuit C2 in watts?") == "compute"


def test_offline_agent_answers_canonical_questions(samples):
    """Every canonical compute question and every compliance question, in all four domains."""
    from cad_copilot.spec_content import SPECS
    qs = [q for q in build(str(samples)) if q.get("variant") == "canonical" or q["kind"] == "compliance"]
    assert {q["domain"] for q in qs} == {"building", "electrical", "electronic", "mechanical"}
    agents = {}
    wrong = []
    for q in qs:
        key = (q["drawing"], q["spec"])
        pdf = str(samples / SPECS[q["spec"]]["file"]) if q["spec"] else None
        a = agents.setdefault(key, CadCopilot.from_files(str(samples / q["drawing"]), pdf))
        ans = a.answer(q["question"])
        if not score(q, ans.final, ans.text, ans.sources):
            wrong.append((q["question"], q["expected"], ans.final))
    assert not wrong, wrong


class FakeLLM(LLMClient):
    """Scripted LLM: calls one tool, then answers from its result. Tests the tool loop plumbing."""
    name = "fake"

    def complete(self, system, user, image_png=None):
        return "compute"

    def run_tool_loop(self, system, user, tools, executor, max_steps=6):
        assert any(t["name"] == "labeled_regions" for t in tools)
        out = executor("labeled_regions", {"layer": "ROOMS"})
        return f"There are {out['count']} rooms.\nFINAL: {out['count']}", [{"tool": "labeled_regions", "args": {}, "result": out}]


def test_llm_path_uses_tools(samples, manifests):
    a = CadCopilot.from_files(str(samples / "plan-001.dxf"), llm=FakeLLM()).answer("How many rooms?")
    assert a.route == "compute" and a.final == str(manifests["plan-001"]["counts"]["rooms"]) and a.trace
