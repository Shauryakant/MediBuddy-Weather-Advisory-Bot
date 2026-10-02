# Architecture & System Design Document (DESIGN.md)

## 🎯 Executive Summary & Core Engineering Philosophy

The **MediBuddy Weather-Advisory Support Bot** is designed around a non-negotiable safety principle:
**THE MODEL NEVER DECIDES SAFETY ADVICE.**

In healthcare and wellness applications, LLM hallucination or unconstrained safety judgment is unacceptable. Every piece of advice delivered to an end user must trace directly back to an authoritative, human-reviewed Standard Operating Procedure (SOP). The LLM is restricted strictly to:
1. Parsing raw user text into structured intent enums.
2. Evaluating qualitative "fuzzy" rubrics against evidence numbers.
3. Phrasing approved policy guidance text using verified API numbers.

---

## 🏗️ Architectural Decisions & Graph Design

### 1. Real Branching Graph Architecture
The system is implemented as a **LangGraph StateGraph** featuring explicit, non-linear conditional branching:

```
[START] -> parse_intent
              |--> (Out of scope / Unmapped activity) ----> no_guidance ----> [END]
              |--> (Missing location) ---------------------> ask_clarification -> [END]
              |--> (Valid intent) -------------------------> geocode
                                                                |--> (API/Geo error) -> failure_node -> [END]
                                                                |--> (Success) -------> fetch_weather
                                                                                           |--> (API error) -> failure_node -> [END]
                                                                                           |--> (Success) ----> match_sops
                                                                                                                   |--> (Unmapped) -> no_guidance -> [END]
                                                                                                                   |--> (0 Triggered) -> no_trigger_node -> [END]
                                                                                                                   |--> (>=1 Triggered) -> resolve_conflicts
                                                                                                                                              |
                                                                                                                                        compose_answer
                                                                                                                                              |
                                                                                                                                        validate_answer
                                                                                                                                              |--> (Pass) ----> update_session -> [END]
                                                                                                                                              |--> (Fail 1x) -> compose_answer (retry)
                                                                                                                                              |--> (Fail 2x) -> deterministic_render -> update_session -> [END]
```

### 2. Node Responsibilities
- `parse_intent`: LLM structured output parser extracting `{in_scope, location_text, activity_tag, audience_tag, time_ref}`. Inherits prior session state on follow-ups.
- `geocode`: Resolves city names using Open-Meteo Geocoding API (`/v1/search`).
- `fetch_weather`: Computes the union of all metrics required by active SOPs and fetches hourly/current data from Open-Meteo.
- `match_sops`: Loads SOPs fresh from disk (enabling hot reload). Evaluates threshold conditions deterministically and fuzzy rubrics via schema-constrained LLM calls.
- `resolve_conflicts`: Ranks matched SOPs to select 1 Headline Primary SOP and up to 2 Secondary SOPs ("Also applicable").
- `compose_answer`: Phrasing node that receives ONLY structured guidance text and allowed API numbers.
- `validate_answer`: Deterministic validator node verifying number grounding and SOP citations.
- `deterministic_render`: Hardened fallback node generating replies directly from YAML guidance templates when LLM validation fails twice.
- `failure_node`, `no_guidance`, `ask_clarification`, `no_trigger_node`: Hardened, honest fallback nodes.

---

## 🤖 Deterministic Code vs LLM Boundaries

| Component / Task | Implementation Mode | Rationale |
|---|---|---|
| SOP Loading & Schema Validation | **Deterministic** | Enforces strict Pydantic v2 schemas; rejects malformed YAML cleanly without crashing. |
| Required Weather Field Discovery | **Deterministic** | Computes set union of all metrics referenced in SOPs at runtime. |
| Taxonomy Extraction | **Deterministic** | Dynamic list of activity/audience tags generated from SOPs. |
| Geocoding & Weather Fetch | **Deterministic** | Direct HTTP calls via `httpx` with 5s timeout & retries. |
| Time Window Aggregation | **Deterministic** | Exact metric slicing (`value`, `max`, `min`, `sum`, `mean`, `delta`) over named windows. |
| Threshold SOP Condition Evaluation | **Deterministic** | Pure Boolean logic tree matching (`>`, `>=`, `<`, `<=`, `==`, `in`). |
| Conflict Resolution & Ranking | **Deterministic** | Fixed ranking: Overrides > Severity > Priority > Specificity. |
| Intent Parsing | **LLM** | Extracts structured enums from natural language queries; isolated from prompt injection. |
| Fuzzy SOP Rubric Judgment | **LLM** | Evaluates qualitative rubrics against evidence numbers, constrained to enum `{good, mixed, poor}`. |
| Reply Phrasing | **LLM** | Polishes approved guidance text; outputs are strictly validated against API numbers and SOP citations. |
| Number & Citation Validation | **Deterministic** | Regex & set-matching verification enforcing 100% data grounding. |
| Fallback & Error Rendering | **Deterministic** | Zero LLM calls when APIs fail, location is missing, or validation retries fail. |

---

## ⚡ Conflict Resolution Policy

When multiple SOPs trigger for the same question (e.g. high wind AND high UV on a cycling query), the system resolves conflicts deterministically in `app/resolver.py`:

1. **Overrides First**: Any SOP marked `overrides: "all"` (e.g., `SOP-SIT-001` Active Heavy-Rain System) immediately outranks all other SOPs and leads the answer.
2. **Severity Hierarchy**: `danger` (4) > `warning` (3) > `caution` (2) > `info` (1).
3. **Priority Integer**: Integer tiebreaker within the same severity level (e.g. priority 80 beats priority 60).
4. **Specificity**: SOPs matching specific activity/audience tags outrank wildcard `*` SOPs.

**Headline vs Secondary SOPs**:
The highest-ranked SOP is designated as the **Primary SOP** and forms the main headline advice. To prevent hiding real secondary hazards, up to 2 additional triggered SOPs are surfaced under an explicit **"Also applicable"** section.

---

## 🌧️ Composite-Signal Modeling of Heavy Rain (`SOP-SIT-001`)

Severe weather events like IMD-flagged low-pressure systems or monsoon depressions cannot be captured by a single static temperature or wind threshold. The reason is "bigger than any single threshold."

In `sops/sop_sit_001_heavy_rain.yaml`, this is modeled using **composite meteorological signals**:
- 24-hour accumulated rainfall sum >= 64.5 mm (IMD's heavy rainfall lower bound).
- OR: 12-hour rainfall sum >= 40.0 mm AND 24-hour sea-level pressure drop (`pressure_msl.delta`) <= -4.0 hPa (indicating rapid cyclonic/low-pressure deepening).
- OR: Sustained heavy rain/thunderstorm weather codes (`weather_code in [63, 65, 81, 82, 95, 96, 99]`) combined with 24h precip sum >= 30 mm.

**Honest Disclaimer**:
While `SOP-SIT-001` detects real meteorological low-pressure signals from Open-Meteo data, it is a proxy model and not an official IMD warning feed. Guidance text explicitly advises users to verify official IMD alerts.

---

## 🔄 SOP-INF-001 vs No-Trigger Node Resolution

To resolve ambiguity between benign weather guidance and unflagged activities:

1. **`SOP-INF-001` (Pleasant Weather SOP)**: Triggers explicitly when weather metrics satisfy strict ideal conditions (e.g. 16°C <= temp <= 28°C, wind <= 15 km/h, rain prob <= 15%). Its guidance text includes an explicit safety disclaimer: *"Weather conditions look pleasant... Please note: weather can change, this is not a guarantee of safety — stay alert to local weather updates."*
2. **`no_trigger_node`**: Reached when an activity IS covered in policy, but current readings fail to trigger any risk SOP AND fail to meet the ideal pleasant criteria of `SOP-INF-001` (e.g. 31°C temp, 12 km/h wind). It deterministically outputs: *"None of our SOPs flagged a risk for {activity} at current readings: [numbers]. That's not a guarantee of safety, please use your own judgment and check official alerts."*

---

## 💬 Session Memory & State Representation

Session memory is managed using LangGraph's `MemorySaver` checkpointer with `thread_id` set to the Streamlit session ID:

- **State Persistence**: Rather than feeding raw unconstrained message history into LLM prompts, the graph maintains a structured `SessionContext` containing:
  - `last_location` and `last_coords`
  - `last_activity` and `last_audience`
  - `last_time_ref`
  - `last_decision_log` (Primary SOP ID, severity, verdict, and key numbers)
- **Turn Inheritance**: On follow-up queries like *"what about this evening instead?"*, `parse_intent` inherits `last_location` ("Bhopal") and `last_activity` ("cycling") while updating `time_ref` to "this_evening". The weather module re-fetches live forecast data for the new evening window.

---

## ⚠️ Honest Limitations & Gaps

1. **Placeholder Threshold Values**: All numerical thresholds in `sops/*.yaml` are sensible defaults tailored for India, but are explicitly marked as *placeholder values pending domain expert review*.
2. **Open-Meteo Capabilities**: If a policy requires a metric not supplied by Open-Meteo (e.g., real-time river water levels or air quality index AQI), adding that rule would require extending `geo_weather.py` with an additional API client.
3. **Fuzzy LLM Non-Determinism**: While fuzzy SOP verdicts are constrained to `{good, mixed, poor}`, the LLM judge invocation introduces minor non-determinism across runs, mitigated by temperature=0.
4. **Single-Process Deployment**: Session memory uses in-memory `MemorySaver`. For high-scale production, a persistent checkpointer (e.g., PostgresSaver or Redis) and rate-limiting proxy should be deployed.
