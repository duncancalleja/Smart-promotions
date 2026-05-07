# Provider campaign cost calculator & AM spend dashboard — how they work

This note explains the **logic and data flow** behind two companion tools (static HTML + JavaScript, no server-side math):

| Tool | Typical file | Role |
|------|----------------|------|
| **Provider campaign cost calculator** | `campaign-cost-calculator.html` / `provider_campaign_cost_calculator_roi_historic.html` | Scenario planning for **one provider at a time**: weekly cost split (Bolt vs provider), optional **ROI / incremental GMV** view, CSV or embedded cohort data. |
| **Campaign spend by account manager (AM)** | `am_spend_dashboard.html` | **Portfolio view**: all OPS campaigns rolled up by AM, week, type, and reason; **estimated** weekly cost from the same core mechanics where possible, plus **history- and calibration-aware** extras. |

They share the same **product mental model** (discount types, cost share, MOV, segments) but differ in **scope** (single provider vs entire sheet) and in **where “ground truth”** comes from (uploaded weekly rows vs OPS sheet rows + `camp_history`).

---

## Part A — Provider campaign cost calculator

### A.1 What the tool is for

- Answer: *“If we run this promotion for X weeks at this discount and cost split, what does it **cost** Bolt and the provider per week / in total?”*
- Optionally: *“What **incremental GMV** might we attach to that spend for ROI storytelling?”* — clearly separated from the **cash cost** math.

### A.2 Data modes

1. **Manual entry**  
   You type weekly orders, AOV, segment, discount parameters. **No** provider row exists in `providerDB`, so **peer‑GMV calibration** and weekly‑derived signals do **not** apply (`peerRoiScale = 1`, no weekly spend sensitivity).

2. **Embedded / uploaded provider data**  
   - **Per country**: JSON such as `data/<cc>-calc.json` is fetched; rows populate `providerDB` with totals and (when present) **synthetic or aggregated weekly series** for volatility.  
   - **CSV upload**  
     - **Long format**: one row per provider per week; column mapper for id, week, orders, GMV, AOV, optional segment, optional **campaign_spend**.  
     - **Wide format**: pivoted weeks as columns; the parser detects spend-like columns and sums them into `week.spend`.

When `providerDB` is populated, the tool **rebuilds a peer index** (`rebuildPeerRoiIndex`) sorted by **log(average weekly GMV)** within segment (or all providers if the segment pool is too small).

### A.3 Cost estimate (`est`) — what drives the € numbers

The function `est(orders, aov, disc, type, share, …)` computes **expected weekly subsidy cost**:

- **Base volume**: weekly orders × AOV ⇒ weekly GMV (for context and %‑of‑GMV labels).
- **Audience**: For Bolt+‑only scenarios, eligible orders are scaled by **Bolt+ penetration** (default 25%).
- **Discount types**  
  - **Menu / item discount**: discount percent, **redemption** rates (`REDEMPTION`), and for item discounts a **basket share** for how much of the basket the discount applies to.  
  - **Free delivery**: uplift for FD, redemption, **cap** vs average delivery fee assumptions.  
  - **Bolt+ free delivery**: fixed uplift assumption; provider share forced to 0 in the UI flow.

- **MOV (minimum order value)**: If MOV > 0, the model uses a **log‑normal** order‑value distribution (coefficient of variation `cv`, from defaults or from uploaded weekly AOV dispersion) to estimate what fraction of orders **qualify** and the **conditional mean basket** above MOV (`movQualifyingRate`).

**Important design choice:** `UPLIFT` for menu/item discounts in the cost path is set to **zero** in the ROI‑historic build because **baseline weekly orders are already observed**; the tool does **not** inflate order counts again for **cost**. Uplift is reserved for **ROI / incremental story**, not double‑counting volume in the cost line.

Output includes **provider vs Bolt share** of `total` using the **cost share** slider.

### A.4 ROI panel — separate from cost

The ROI block uses **`ROI_UPLIFT`** (and `ROI_UPLIFT_FD` for free delivery): a **fractional incremental orders** curve keyed by discount depth — **only for incremental GMV**, not added again into the same cost formula as order uplift.

That base incremental rate is then **scaled** (bounded multipliers) using whatever signals exist:

| Signal | Source | Effect on ROI uplift |
|--------|--------|----------------------|
| **Order / AOV volatility** | Weekly orders; weekly AOV CV from uploaded weeks, or `estimatedCV` / `estimatedOrderCV` | Higher volatility ⇒ slightly **lower** uplift multiplier (conservative). |
| **Promo sensitivity** | Weekly `spend` vs `orders` (≥10 weeks, spend variance > 0) | Rough elasticity ⇒ `promoSensitivityRatioFromWeeks` (not causal). |
| **Peer GMV cohort** | Nearest neighbors in **log(avgGMV)** in same **segment** when enough peers | Compares this provider’s **campaign intensity** \((campBolt + campMerch) / totalGMV\) and **avg weekly orders** to peer **medians**; produces `peerRoiUpliftScale` between ~0.7 and ~1.35. |

**Repeat / “lifetime” GMV multiplier** (for revenue‑per‑€ invested, not for weekly cost):

1. If **≥10 weekly order points**: `repeatMultiplierFromWeeklyOrders` — compares **forward** multi‑week order sums vs a **median baseline**; maps persistence into a multiplier (clamped, default legacy flavor ~4× when flat).  
2. Else if **embedded campaign spend + GMV** exist: `repeatMultiplierFromCampaignIntensity` — higher sustained marketing intensity ⇒ higher bounded multiplier.  
3. Else: **default 4×** (explicit legacy assumption for ROI narrative only).

### A.5 Views: provider / vendor / group

Aggregates roll up children so you can compare **brand** or **group** level averages; peer logic still keys off the **aggregated** row’s `avgGMV` and segment when present.

### A.6 Campaign stack

You can **stack** multiple scenarios; the UI sums costs and combines **incremental GMV × repeat multiplier** across stacked campaigns for a **portfolio‑style** ROI headline. (Still scenario math, not accounting.)

### A.7 Limitations (share with stakeholders)

- **Not causal inference** — especially spend↔orders sensitivity and peer comparisons.  
- **ROI uplift tables** are **assumptions** for communication, not finance‑grade attribution.  
- **Embedded snapshots** are point‑in‑time; refresh the JSON pipeline when data drifts.  
- **Manual mode** cannot personalize ROI the same way as a matched `providerDB` row.

---

## Part B — AM spend dashboard (`am_spend_dashboard.html`)

### B.1 What it shows

- **Operational campaigns** from Google Sheets (per country), with filters: **week**, **campaign type**, **investment reason**, **cost bearer**, text search.  
- **Summary cards**: count of campaigns / providers, **total estimated cost per week**, Bolt vs provider split, optional **weekly Bolt budget** bar (localStorage per country).  
- **Chart vs table**: same underlying rows; chart = spend stacked by AM; table = sortable detail.

### B.2 Where numbers come from

Each campaign row (`_OPS_CAMPAIGNS`) carries provider metrics (weekly orders derived from totals over `WEEKS_IN_DATA`, AOV, segment, discount, cost share %, MOV, etc.).

**`estimateCampaignCost(c)`** chooses the path:

1. **History‑based** (`_historyEstimate`): looks up **`camp_history`** for that **provider × campaign category × discount tier**. If the campaign was “turned off” in history, history is skipped.  
   - Can **blend** with **recent actuals** (`_recentActualsAvg`) when those exist (70% recent / 30% history in the blend path in code).  
2. **Formula fallback** (no usable history): same structural pieces as the calculator — **MOV / log‑normal**, segment‑scaled **`getUpliftScaled`**, **`getRedemption`**, FD fee caps — driven from **`PARAM_DEFAULTS`** / **calibration** rather than the single‑file `ROI_UPLIFT` table.

So the dashboard is **“history first, calibrated formula second”** at scale; the single‑provider calculator is **“explicit scenario + richer ROI personalization when you have rows.”**

### B.3 Calibration & accuracy tooling

- **Calibration panel** (`runCalibration`, localStorage): adjusts segment defaults used in formula fallback.  
- **Snapshots**: save estimates vs later **actuals** (CSV upload), export/import JSON, optional **Databricks check** button where wired.  
- **Google Sheet webhook**: optional push of snapshot rows to Sheets; **sheet-config.json** documents country sheet IDs / GIDs for team‑wide defaults.

### B.4 Navigation

Header links connect **AM Portfolio**, **Cost Calculator**, and country selector — same static site, different HTML entry points.

---

## Part C — Quick comparison

| Topic | Calculator | AM spend dashboard |
|-------|------------|----------------------|
| Primary user question | “What if **this** provider runs **this** deal?” | “What are **we** spending across **all** AMs / campaigns?” |
| Order uplift in **cost** | Effectively **0** (orders are observed) | History or formula via **`estimateCampaignCost`** |
| ROI / incremental GMV | Explicit panel + repeat + peers | Focus on **cost** rollups; history for **accuracy** of estimates |
| Data ingestion | JSON + CSV | Google Sheet + JSON configs + snapshots |

---

## Sharing this document

- **As Markdown**: send this `.md` file; any editor renders it.  
- **As PDF**: open in **VS Code / Cursor**, **Typora**, **MacDown**, or **GitHub** (paste into a gist or repo file) and **Print → Save as PDF**.  
- **Canonical paths** (your machine):  
  - `~/Documents/Bolt food/CAMPAIGN_CALCULATOR_AND_AM_SPEND_GUIDE.md`

---

*Generated as a plain reference for Bolt Food internal use. Numbers and constants in the HTML/JSON builds may change over time; read the source comments in the relevant `<script>` blocks for the exact version you ship.*
