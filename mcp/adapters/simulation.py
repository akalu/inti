"""
INTI — Simulation LLM Adapter
===================================
Deterministic, context-aware responses for testing without API keys.
"""

from __future__ import annotations

import json

from mcp.adapter import LLMAdapter


class SimulationAdapter(LLMAdapter):
    """Simulates LLM responses based on prompt keywords."""

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self._call_count += 1
        p = prompt.lower()

        # Genesis acknowledgments
        if "genesis" in p or "initialization" in p or "instantiat" in p:
            return json.dumps({
                "status": "ACTIVE",
                "acknowledgment": f"System initialized and operational. Ready to serve the constellation.",
                "subsystems": "All subsystems nominal.",
            })

        # Diagnostic / health
        if "diagnos" in p or "error" in p or "health" in p or "fault" in p:
            return json.dumps({
                "diagnosis": "No critical faults detected.",
                "severity": "LOW",
                "recommendation": "Continue normal operation.",
                "confidence": 0.85,
            })

        # Repair
        if "repair" in p or "patch" in p or "fix" in p:
            return json.dumps({
                "action": "repair",
                "target": "detected_component",
                "patch": "# Simulated repair patch\npass",
                "risk": "LOW",
                "authorized": True,
            })

        # Decision / evaluation
        if "decide" in p or "decision" in p or "evaluat" in p or "priorit" in p:
            return json.dumps({
                "decision": "Proceed with recommended course of action.",
                "courses_of_action": [
                    {"option": "A", "priority": 1, "rationale": "Optimal outcome with minimal risk."},
                    {"option": "B", "priority": 2, "rationale": "Safe alternative with moderate benefit."},
                ],
                "verdict": "Option A recommended.",
                "confidence": 0.9,
            })

        # Laws / rules / ethics
        if "law" in p or "rule" in p or "ethic" in p or "veto" in p or "violat" in p:
            return json.dumps({
                "assessment": "No law violations detected.",
                "vetoed": False,
                "advisory": "Action is within ethical and operational bounds.",
                "confidence": 0.95,
            })

        # Knowledge / search / intellect
        if "knowledge" in p or "search" in p or "librari" in p or "abstract" in p:
            return json.dumps({
                "results": [
                    {"source": "knowledge_base", "content": "Relevant knowledge found.", "confidence": 0.8},
                ],
                "total_results": 1,
            })

        # Understanding / synthesis / possibility
        if "understand" in p or "synthes" in p or "possibil" in p:
            return json.dumps({
                "understanding": "Situation analyzed from all perspectives.",
                "appearances": "Current state assessment complete.",
                "possibilities": [
                    {"scenario": "positive", "probability": 0.6},
                    {"scenario": "negative", "probability": 0.2},
                    {"scenario": "neutral", "probability": 0.2},
                ],
            })

        # Presentation / output / render
        if "present" in p or "render" in p or "display" in p or "output" in p:
            return json.dumps({
                "rendered": True,
                "format": "text",
                "content": "Information presented to the user.",
            })

        # Tool invocation validation (Reason validates tools)
        if "validate_tool" in p or ("tool" in p and "risk" in p):
            return json.dumps({
                "authorized": True,
                "reasoning": "Simulated validation — tool invocation within acceptable risk parameters.",
                "advisory": "Proceed with caution.",
            })

        # Tool-augmented generation (when tool schemas are injected)
        if "available tools" in p and ("file" in p or "read" in p or "write" in p):
            return json.dumps({
                "tool_call": {
                    "name": "file_manager",
                    "arguments": {"action": "list", "path": "."},
                },
            })

        if "available tools" in p and ("shell" in p or "command" in p or "run" in p):
            return json.dumps({
                "tool_call": {
                    "name": "shell",
                    "arguments": {"command": "echo INTI active"},
                },
            })

        # Sensory / environment
        if "sensor" in p or "environment" in p or "state" in p:
            return json.dumps({
                "environment": "stable",
                "external_state": "nominal",
                "internal_state": "operational",
                "anomalies": [],
            })

        # Contemplation / idea / concept
        if "contemplat" in p or "idea" in p or "concept" in p or "think" in p:
            return json.dumps({
                "contemplation": "A new idea has emerged from the deliberation.",
                "idea_origin": "Understanding",
                "concept_status": "developing",
                "nexus_assembly": "pending",
            })

        # Default
        return (
            f"[SIM] Simulated response #{self._call_count} for: "
            f"{prompt[:100]}..."
        )
