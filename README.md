# GDELT Global Misinformation Analysis

Event-level analysis of misinformation and disinformation as a global, data-driven phenomenon — using structured news event data rather than platform-specific social media posts. By combining the [GDELT](https://www.gdeltproject.org/) Global Knowledge Graph with articles from major outlets (Reuters, BBC, Al Jazeera, AP), this project builds a structured dataset of misinformation-related events capturing **what** happened, **where** it occurred, and **which narratives** were involved.

## Research Questions

1. What types of misinformation themes appear in global news reporting?
2. Where are these events geographically concentrated?
3. Under what political, economic, or public health conditions does misinformation activity increase?

## Methods

| Question | Method | Tools |
|---|---|---|
| What themes appear? | LDA topic modelling | `gensim` |
| Where do events cluster? | Spatial analytics — DBSCAN, Moran's I, KDE | `scikit-learn`, `geopandas`, `libpysal`, `esda` |
| What drives event spikes? | Count-based regression — Poisson, Negative Binomial | `statsmodels` |

Together, these produce a data-driven map and model of global misinformation: what narratives dominate, where they cluster geographically, and which political, economic, or public health conditions are associated with spikes in activity.

## Repository Structure

```
.
├── gdelt_analytical_dataset_v1.xlsx      # Event-level input dataset (GDELT-derived)
├── gdelt_misinformation_analysis.ipynb   # Full analysis pipeline (Jupyter notebook)
├── README.md
└── outputs/                              # Generated on first run — cleaned data & results
    ├── cleaned_events_with_topics.csv
    ├── country_month_panel.csv
    ├── theme_frequencies.csv
    ├── topic_vs_tone.csv
    └── negative_binomial_irr.csv
```

## Dataset

`gdelt_analytical_dataset_v1.xlsx` contains one row per misinformation-related event, with the following key fields:

- **Identifiers / time:** `Record_ID`, `Date`, `Year`, `Month`, `Year_Month`
- **Geography:** `Country`, `Latitude`, `Longitude`
- **Content:** `Themes` (semicolon-separated GDELT theme tags), `Theme_Count`, `Misinfo_Flag`
- **Tone:** `Tone_Overall`, `Tone_Positive`, `Tone_Negative`, `Tone_Polarity`, `Tone_Activity`, `Tone_SelfGroup`
- **Categories:** `Context_Category`, `Tone_Category`

## Getting Started

### 1. Requirements

Python 3.9+ (via Anaconda recommended). Required packages:

```
pandas numpy matplotlib seaborn scikit-learn statsmodels gensim scipy
geopandas libpysal esda shapely
```

### 2. Install dependencies

**Option A — from an Anaconda Prompt / terminal:**

```bash
conda install -c conda-forge pandas numpy matplotlib seaborn scikit-learn statsmodels geopandas libpysal esda -y
pip install gensim
```

**Option B — from inside the notebook:**
The notebook's second cell installs everything for you via `%pip install`. Run it once, then restart the kernel (**Kernel → Restart**) before running the rest of the notebook.

### 3. Run the analysis

1. Keep `gdelt_analytical_dataset_v1.xlsx` and `gdelt_misinformation_analysis.ipynb` in the same folder.
2. Open the notebook in Jupyter Notebook / Jupyter Lab.
3. Run all cells top to bottom (**Cell → Run All**, or step through with Shift+Enter).
4. Results (plots, tables, model summaries) render inline under each cell. Cleaned data and key result tables are also written to `outputs/` by the final cell.

## Pipeline Overview

1. **Load & inspect** — read the Excel dataset, check structure and key columns
2. **Clean & preprocess** — deduplicate, filter to confirmed misinformation events, handle missing values, standardise country names, build time variables
3. **Theme identification (LDA)** — tokenise `Themes`, build a gensim corpus, fit LDA across a range of topic counts, select the best by coherence (`c_v`), assign each event a dominant topic
4. **Exploratory analysis** — theme frequency, dominant narratives by country, tone distributions, tone by topic
5. **Spatial analysis** — map events, run DBSCAN clustering (with a k-distance plot to guide `eps`), compute Moran's I on country-level event counts and tone, generate a KDE hotspot map
6. **Contextual variables** — derive `Political_Context`, `Economic_Context`, `Health_Context` flags from theme tags, aggregate to a Country × Month panel
7. **Regression modelling** — fit Poisson regression, test for overdispersion, fit Negative Binomial regression (with MLE-estimated dispersion), report Incidence Rate Ratios (IRRs)
8. **Final outputs** — summary tables, an IRR effect plot, and exported CSVs for reporting

## Notes for Interpretation

- **Themes:** report which topics dominate overall and how that varies by country.
- **Geography:** report DBSCAN cluster count/locations, whether Moran's I indicates significant spatial clustering (vs. randomness), and where KDE hotspots fall.
- **Context:** report which of the Political/Economic/Health context proportions have an IRR significantly different from 1, and in which direction.
- `EPS`/`MIN_SAMPLES` (DBSCAN) and `NUM_TOPICS` (LDA) are analytic choices made in the notebook — revisit and justify them for your own write-up rather than leaving them at their defaults.

## License

Add your preferred license here (e.g. MIT).