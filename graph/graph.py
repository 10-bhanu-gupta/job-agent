# graph/graph.py
#
# This file assembles the LangGraph multi-agent graph.
# It wires all agents together, defines the execution order,
# and inserts the human-in-the-loop interrupt checkpoint.
#
# CONCEPT — How LangGraph graphs work
# -------------------------------------
# A LangGraph graph is a directed graph where:
#   - NODES are units of work (our agents, each a Python function)
#   - EDGES define what runs after what
#   - CONDITIONAL EDGES let the graph make routing decisions dynamically
#   - The CHECKPOINTER saves state to PostgreSQL after every node completes
#
# EXECUTION FLOW
# --------------
#   START
#     │
#     ▼
#   scrape_agent ──────────────────────────────┐
#     │                                        │
#     ▼                                        ▼
#   funding_intel_agent              (runs in parallel — future v2)
#     │
#     ▼
#   scoring_agent
#     │
#     ▼
#   contact_finder_agent
#     │
#     ▼
#   outreach_agent
#     │
#     ▼
#   ⏸ INTERRUPT (human reviews in dashboard)
#     │
#     ▼ (resumes after approval)
#   tracker_agent
#     │
#     ▼
#   END

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState

# ---------------------------------------------------------------------------
# IMPORT AGENTS
# We import each agent function here. They don't exist yet — we'll build
# them one by one. For now they're stubbed out below so the graph compiles.
# ---------------------------------------------------------------------------

# NOTE: Once we build each agent, we'll replace these stubs with real imports:
# from agents.scrape_agent import scrape_agent
from agents.scrape_agent import scrape_agent
# from agents.funding_intel_agent import funding_intel_agent
# from agents.scoring_agent import scoring_agent
from agents.scoring_agent import scoring_agent
# from agents.contact_finder_agent import contact_finder_agent
# from agents.outreach_agent import outreach_agent
# from agents.tracker_agent import tracker_agent


# ---------------------------------------------------------------------------
# STUB AGENTS
# These are temporary placeholder functions so we can compile and test the
# graph structure before building the real agents.
#
# CONCEPT — What is a LangGraph node function?
# Each node is simply a Python function that:
#   1. Receives the current AgentState as its only argument
#   2. Does some work
#   3. Returns a DICT containing only the keys it wants to update
#      (NOT the full state — LangGraph merges the returned dict into state)
#
# This is important: you never return the full state from a node.
# You only return the fields you changed.
# ---------------------------------------------------------------------------


def funding_intel_agent(state: AgentState) -> dict:
    """
    STUB — will be replaced by the real FundingIntelAgent.
    Uses Tavily to search Entrackr for recently funded companies.
    Returns: {"funded_companies": [...]}
    """
    print("💰 [FundingIntelAgent] Running... (stub)")
    return {
        "pipeline_status": "running",
        "last_updated": "stub_timestamp"
    }


def contact_finder_agent(state: AgentState) -> dict:
    """
    STUB — will be replaced by the real ContactFinderAgent.
    Uses Tavily + Proxycurl + Hunter.io to find hiring manager details.
    Returns: {"contacts_found": [...]}
    """
    print("👤 [ContactFinderAgent] Running... (stub)")
    return {
        "pipeline_status": "running",
        "last_updated": "stub_timestamp"
    }


def outreach_agent(state: AgentState) -> dict:
    """
    STUB — will be replaced by the real OutreachAgent.
    Uses Claude API to draft personalised cold emails + LinkedIn DMs.
    Returns: {"outreach_drafts": [...]}

    NOTE: This node sits JUST BEFORE the interrupt checkpoint.
    The graph will pause after this node runs and wait for human approval.
    """
    print("✍️  [OutreachAgent] Running... (stub)")
    return {
        "pipeline_status": "paused",
        "last_updated": "stub_timestamp"
    }


def tracker_agent(state: AgentState) -> dict:
    """
    STUB — will be replaced by the real TrackerAgent.
    Writes final state (approved outreach, sent emails, job statuses) to PostgreSQL.
    Returns: {"pipeline_status": "complete"}

    NOTE: This node runs AFTER the human approves outreach drafts.
    It resumes the graph from the interrupt checkpoint.
    """
    print("📊 [TrackerAgent] Running... (stub)")
    return {
        "pipeline_status": "complete",
        "last_updated": "stub_timestamp"
    }


# ---------------------------------------------------------------------------
# BUILD THE GRAPH
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None):
    """
    Assembles and compiles the LangGraph multi-agent graph.

    CONCEPT — Why a function instead of module-level code?
    We wrap graph construction in a function so we can pass different
    checkpointers depending on context:
      - MemorySaver (in-memory)  → for local development and testing
      - PostgresSaver             → for production (saves state to Cloud SQL)

    Args:
        checkpointer: a LangGraph checkpointer instance.
                      Defaults to MemorySaver for local dev.

    Returns:
        A compiled LangGraph graph ready to invoke.
    """

    if checkpointer is None:
        # MemorySaver stores state in RAM — useful for testing
        # State is lost when the process ends
        # We'll swap this for PostgresSaver when we connect to Cloud SQL
        checkpointer = MemorySaver()

    # Step 1 — Create the graph, telling it what state schema to use
    # AgentState is the TypedDict we defined in graph/state.py
    workflow = StateGraph(AgentState)

    # Step 2 — Register each agent as a named node
    # Format: workflow.add_node("node_name", function)
    # The node_name is how we reference it when adding edges
    workflow.add_node("scrape", scrape_agent)
    workflow.add_node("funding_intel", funding_intel_agent)
    workflow.add_node("scoring", scoring_agent)
    workflow.add_node("contact_finder", contact_finder_agent)
    workflow.add_node("outreach", outreach_agent)
    workflow.add_node("tracker", tracker_agent)

    # Step 3 — Wire the edges (execution order)
    # START is a built-in LangGraph constant for the entry point
    workflow.add_edge(START, "scrape")
    workflow.add_edge("scrape", "funding_intel")
    workflow.add_edge("funding_intel", "scoring")
    workflow.add_edge("scoring", "contact_finder")
    workflow.add_edge("contact_finder", "outreach")
    workflow.add_edge("outreach", "tracker")
    workflow.add_edge("tracker", END)

    # Step 4 — Compile the graph
    # interrupt_before=["tracker"] tells LangGraph to PAUSE the graph
    # BEFORE the tracker node runs, and wait for human input.
    #
    # CONCEPT — How interrupt_before works:
    # When the graph reaches the "outreach" → "tracker" edge, instead of
    # immediately running "tracker", LangGraph:
    #   1. Saves the entire current state to the checkpointer (PostgreSQL)
    #   2. Returns control to your code with status "interrupted"
    #   3. Waits — the graph is now "frozen" in the database
    #
    # Your Streamlit dashboard reads this frozen state, shows you the
    # outreach drafts, and lets you approve or reject each one.
    #
    # When you click Approve, your code calls graph.invoke() again with
    # the same thread_id — LangGraph loads the frozen state from the DB
    # and resumes from exactly where it stopped.
    #
    # This is called "persistence" and it's one of LangGraph's most
    # powerful production features.
    graph = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["tracker"]
    )

    return graph


# ---------------------------------------------------------------------------
# QUICK TEST — run this file directly to verify the graph compiles
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Building graph...")
    graph = build_graph()
    print("✅ Graph compiled successfully")

    # get_graph().draw_ascii() prints a text diagram of your graph
    # Useful for quickly verifying the structure looks right
    print("\nGraph structure:")
    print(graph.get_graph().draw_ascii())