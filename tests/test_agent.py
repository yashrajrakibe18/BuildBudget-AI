"""Graph wiring test with a scripted FAKE tool-calling model (no network/LLM).
It proves: supervisor routing -> ReAct specialist -> real tool execution (logged) -> final answer,
and the clarification path. It does NOT measure real-LLM quality (see docs/EVALUATION.md)."""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import models as m
from app.ai import tools as T
from app.ai.graph import run_chat


class ScriptedModel(BaseChatModel):
    supervisor_reply: str
    @property
    def _llm_type(self): return "scripted"
    def bind_tools(self, tools, **kw): return self
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        sys = str(messages[0].content)
        if "SUPERVISOR" in sys:
            msg = AIMessage(content=self.supervisor_reply)
        elif "VERIFIER" in sys:
            msg = AIMessage(content="FINAL: " + str(messages[-1].content)[-200:])
        elif any(isinstance(x, ToolMessage) for x in messages):
            msg = AIMessage(content="tool said: " + [x for x in messages if isinstance(x, ToolMessage)][-1].content)
        else:
            msg = AIMessage(content="", tool_calls=[{"name": "estimate_tile_quantity", "id": "c1",
                            "args": {"area_sqft": 180, "tile_length": 24, "tile_width": 24}}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _user(db):
    u = m.User(email="agent@t.io", name="a", password_hash="x", role="homeowner")
    db.add(u); db.commit(); return u


def test_graph_executes_real_tool(db):
    u = _user(db)
    tools = T.build_tools(db, u, None)
    llm = ScriptedModel(supervisor_reply='{"agents": ["estimation"], "missing_info": []}')
    res = run_chat(llm, tools, "tiles for 12x15 room?")
    assert res["agents"] == ["estimation"] and res["answer"].startswith("FINAL")
    log = db.query(m.ToolExecution).filter_by(user_id=u.id, tool="estimate_tile_quantity").one()
    assert log.status == "ok" and '"final_quantity": 50' in log.result


def test_graph_asks_for_missing_info(db):
    u = _user(db) if not db.query(m.User).filter_by(email="agent@t.io").first() else db.query(m.User).filter_by(email="agent@t.io").first()
    llm = ScriptedModel(supervisor_reply='{"agents": [], "missing_info": ["What wall height?"]}')
    res = run_chat(llm, T.build_tools(db, u, None), "estimate my room")
    assert "What wall height?" in res["answer"] and res["agents"] == []
