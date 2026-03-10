# ---- packages ----
library(tidyverse)
library(rrobot)      # SHASH_out, normal_to_SHASH
library(ggrain)      # geom_rain()
library(shadowtext)
library(patchwork)

# =========================
# 1. Load original data
# =========================
df_bold_auto <- readr::read_tsv("Desktop/ADNI_paper/temp/group_bold.tsv")
df_t1_auto   <- readr::read_tsv("Desktop/ADNI_paper/temp/group_T1w.tsv")

df_bold_inv <- readr::read_csv('Desktop/ADNI_paper/group_bold_inverse.csv')
df_t1_inv   <- readr::read_csv('Desktop/ADNI_paper/group_T1w_inverse.csv')

# Quickly check names so you can adjust the metric vectors below:
 names(df_bold_auto)
 names(df_t1_auto)
 names(df_bold_inv)
 names(df_t1_inv)

# =========================
# 2. Automatic thresholds (upper tail, SHASH/MAD)
# =========================

compute_thresh <- function(x) {
  x <- x[is.finite(x)]
  if (length(x) == 0) return(list(val = NA_real_, method = "NA"))
  if (length(unique(x)) < 8 || length(x) < 30) {
    m  <- median(x, na.rm = TRUE)
    md <- mad(x, constant = 1.4826, na.rm = TRUE)
    return(list(val = m + 4 * md, method = "MAD"))
  }
  out <- try({
    fit <- SHASH_out(
      x,
      symmetric   = TRUE,
      thr0        = 2.58,
      thr         = 4,
      upper_only  = TRUE,
      use_isotree = FALSE,
      use_isoplus = TRUE,
      thr_isotree = 0.55
    )
    normal_to_SHASH(
      4,
      fit$SHASH_coef$mu,
      fit$SHASH_coef$sigma,
      fit$SHASH_coef$nu,
      fit$SHASH_coef$tau
    )
  }, silent = TRUE)
  if (inherits(out, "try-error") || !is.finite(out)) {
    m  <- median(x, na.rm = TRUE)
    md <- mad(x, constant = 1.4826, na.rm = TRUE)
    list(val = m + 4 * md, method = "MAD")
  } else {
    list(val = out, method = "SHASH")
  }
}

build_rain_auto <- function(df,
                            metrics,
                            title_prefix = "Dataset",
                            facet_cols   = 3,
                            hist_bins    = 30) {
  # df: wide dataframe
  # metrics: character vector of column names to include
  
  # long data
  df_long <- df %>%
    select(all_of(metrics)) %>%
    pivot_longer(
      cols = everything(),
      names_to = "metric",
      values_to = "value"
    )
  
  # automatic thresholds
  thresholds <- purrr::map_dfr(
    metrics,
    \(nm) {
      res <- compute_thresh(df[[nm]])
      tibble(metric = nm, thresh_val = res$val, method = res$method)
    }
  )
  
  df_long2 <- df_long %>%
    left_join(thresholds, by = "metric")
  
  # outliers: value > threshold
  outlier_stats <- df_long2 %>%
    group_by(metric) %>%
    summarize(
      n       = sum(is.finite(value)),
      n_out   = sum(value > thresh_val, na.rm = TRUE),
      pct_out = 100 * n_out / n,
      .groups = "drop"
    )
  
  df_long2 <- df_long2 %>%
    left_join(outlier_stats, by = "metric") %>%
    mutate(
      metric_label = sprintf("%s\noutliers: %d (%.1f%%)",
                             metric, n_out, pct_out)
    )
  
  ann <- df_long2 %>%
    group_by(metric_label) %>%
    summarize(thresh_val = first(thresh_val), .groups = "drop")
  
  # rainclouds
  p_rain <- ggplot(df_long2, aes(x = 1, y = value)) +
    geom_rain(fill = "gray65", alpha = 0.55, point_size = 0.6) +
    geom_hline(
      data = ann,
      aes(yintercept = thresh_val),
      linetype = "dashed", color = "red", linewidth = 1
    ) +
    shadowtext::geom_shadowtext(
      data = ann %>% filter(is.finite(thresh_val)),
      aes(x = 1, y = thresh_val, label = sprintf("%.3f", thresh_val)),
      hjust = 0.5, vjust = -0.4,
      color = "red", bg.color = "white",
      size = 4.2, fontface = "bold", bg.r = 0.15
    ) +
    facet_wrap(~ metric_label, scales = "free_y", ncol = facet_cols) +
    scale_y_continuous(expand = expansion(mult = c(0.05, 0.15))) +
    labs(
      title = paste0(title_prefix, " – Rainclouds (automatic)"),
      y = "Value", x = NULL
    ) +
    theme_classic() +
    theme(
      axis.text.x  = element_blank(),
      axis.ticks.x = element_blank(),
      strip.text   = element_text(size = 6, lineheight = 0.9,
                                  margin = margin(t = 2, r = 2, b = 2, l = 2)),
      strip.background = element_rect(fill = "grey95", colour = NA),
      plot.margin  = margin(t = 35, r = 10, b = 10, l = 10)
    )
  
  list(
    data       = df_long2,
    thresholds = thresholds,
    p_rain     = p_rain
  )
}

# =========================
# 3. MANUAL thresholds (lower tail)
# =========================

build_rain_manual <- function(df,
                              thresholds_manual,
                              title_prefix = "Dataset",
                              facet_cols   = 3,
                              hist_bins    = 30) {
  # thresholds_manual: tibble with columns metric, thresh_val
  # df: wide df in original space
  
  metrics <- thresholds_manual$metric
  
  df_long <- df %>%
    select(all_of(metrics)) %>%
    pivot_longer(
      cols = everything(),
      names_to = "metric",
      values_to = "value"
    )
  
  df_long2 <- df_long %>%
    left_join(thresholds_manual, by = "metric")
  
  # outliers: value < threshold
  outlier_stats <- df_long2 %>%
    group_by(metric) %>%
    summarize(
      n = sum(is.finite(value)),
      n_out = sum(is.finite(thresh_val) & is.finite(value) & value < thresh_val),
      pct_out = if_else(n > 0, 100 * n_out / n, NA_real_),
      .groups = "drop"
    )
  
  df_long2 <- df_long2 %>%
    left_join(outlier_stats, by = "metric") %>%
    mutate(
      metric_label = sprintf(
        "%s\noutliers: %s (%.1f%%)",
        metric,
        ifelse(is.na(n_out), "NA", as.character(n_out)),
        pct_out
      )
    )
  
  ann <- df_long2 %>%
    group_by(metric_label) %>%
    summarize(thresh_val = first(thresh_val), .groups = "drop")
  
  p_rain <- ggplot(df_long2, aes(x = 1, y = value)) +
    geom_rain(fill = "gray65", alpha = 0.55, point_size = 0.6) +
    geom_hline(
      data = ann %>% filter(is.finite(thresh_val)),
      aes(yintercept = thresh_val),
      linetype = "dashed", color = "red", linewidth = 1
    ) +
    shadowtext::geom_shadowtext(
      data = ann %>% filter(is.finite(thresh_val)),
      aes(x = 1, y = thresh_val, label = sprintf("%.3f", thresh_val)),
      hjust = 0.5, vjust = -0.4,
      color = "red", bg.color = "white",
      size = 4.2, fontface = "bold", bg.r = 0.15
    ) +
    facet_wrap(~ metric_label, scales = "free_y", ncol = facet_cols) +
    scale_y_continuous(expand = expansion(mult = c(0.05, 0.15))) +
    labs(
      title = paste0(title_prefix, " – Rainclouds (manual)"),
      y = "Value", x = NULL
    ) +
    theme_classic() +
    theme(
      axis.text.x  = element_blank(),
      axis.ticks.x = element_blank(),
      strip.text   = element_text(size = 6, lineheight = 0.9,
                                  margin = margin(t = 2, r = 2, b = 2, l = 2)),
      strip.background = element_rect(fill = "grey95", colour = NA),
      plot.margin  = margin(t = 35, r = 10, b = 10, l = 10)
    )
  
  list(
    data       = df_long2,
    thresholds = thresholds_manual,
    p_rain     = p_rain
  )
}

# =========================
# 4. Define metric sets & thresholds
# =========================
# IMPORTANT: Replace the column names below with exactly those in names(df_t1) / names(df_bold)

## ---- T1w ----

# Automatic T1: CNR, SNR, TPM overlaps
t1_auto_metrics <- c(
  "Coefficient of Joint Variation (CJV)",
  "Entropy Focus Criterion (EFC)",
  "Full Width Half Max (FWHM (mm))"
)

# Manual T1: CJV, EFC, FWHM
# Set THESE to your manually derived thresholds in ORIGINAL space:
cnr_t1_thresh = 0.676
snr_t1_thresh = 2.39
tpm_csf_thresh = 0.159
tpm_gm_thresh = 0.449
tpm_wm_thresh = 0.443


t1_manual_thresholds <- tibble::tibble(
  metric     = c(
    "Contrast to Noise Ratio (CNR)",
    "Signal to Noise Ratio (SNR)",
    "Tissue Prob Map (TPM) Overlap CSF",
    "TPM Overlap GM",
    "TPM Overlap WM"
  ),
  thresh_val = c(cnr_t1_thresh, snr_t1_thresh, tpm_csf_thresh, tpm_gm_thresh, tpm_wm_thresh)
)

## ---- BOLD ----

# Automatic BOLD: AOR, AQI, EFC, meanFD, DVARS, FWHM
bold_auto_metrics <- c(
  "AFNIs outlier ratio (AOR)",        # <- adjust to your actual column name
  "AFNIs mean quality index (AQI)",        # <- adjust
  "Entropy Focus Criterion (EFC)",        # <- adjust
  "Framewise disp (meanFD)",    # <- maybe 'fd_mean' or similar
  "Temp deriv RMS var over vox (DVARS)",      # <- adjust
  "Full Width Half Max (FWHM (mm))"        # <- maybe 'fwhm_avg' or similar
)

# Manual BOLD: SNR, tSNR
bold_snr_thresh  <- 1.44
bold_tsnr_thresh <- 0.109

bold_manual_thresholds <- tibble::tibble(
  metric     = c(
    "Signal to Noise Ratio (SNR)",
    "Temporal SNR (TSNR)"
  ),
  thresh_val = c(bold_snr_thresh, bold_tsnr_thresh)
)

# =========================
# 5. Build all four raincloud panels
# =========================

# T1 automatic (CNR/SNR/TPMs)
t1_auto_plots <- build_rain_auto(
  df          = df_t1_auto,
  metrics     = t1_auto_metrics,
  title_prefix = "T1w",
  facet_cols  = length(t1_auto_metrics)
)

# T1 manual (CJV/EFC/FWHM, low values excluded)
t1_manual_plots <- build_rain_manual(
  df               = df_t1_inv,
  thresholds_manual = t1_manual_thresholds,
  title_prefix     = "T1w",
  facet_cols       = length(t1_manual_thresholds$metric)
)

# BOLD automatic (AOR/AQI/EFC/FD/DVARS/FWHM)
bold_auto_plots <- build_rain_auto(
  df          = df_bold_auto,
  metrics     = bold_auto_metrics,
  title_prefix = "BOLD",
  facet_cols  = length(bold_auto_metrics)
)

# BOLD manual (SNR/tSNR, low values excluded)
bold_manual_plots <- build_rain_manual(
  df               = df_bold_inv,
  thresholds_manual = bold_manual_thresholds,
  title_prefix     = "BOLD",
  facet_cols       = length(bold_manual_thresholds$metric)
)

# Check individual panels:
t1_manual_plots$p_rain
t1_auto_plots$p_rain
bold_manual_plots$p_rain
bold_auto_plots$p_rain

# =========================
# 6. Combine manual + automatic per modality
# =========================

t1_manual_n <- 5
t1_auto_n   <- 3

t1_manual_panel <- t1_manual_plots$p_rain + labs(title = NULL)
t1_auto_panel   <- t1_auto_plots$p_rain   + labs(title = NULL)

t1_rain_combined <-
  (t1_manual_panel | t1_auto_panel) +
  plot_layout(
    widths = c(t1_manual_n, t1_auto_n),
    guides  = "collect"
  ) +
  plot_annotation(
    title    = "T1w Image Quality Metrics (IQMs)",
    subtitle = "A: low values excluded (CNR, SNR, TPM overlaps)\nB: high values excluded (CJV, EFC, FWHM)",
    tag_levels = "A"
  ) &
  theme(
    legend.position      = "bottom",
    plot.title.position  = "plot",
    plot.title           = element_text(hjust = 0.5),
    plot.subtitle        = element_text(hjust = 0.5)
  )

t1_rain_combined

bold_manual_n <- 2
bold_auto_n   <- 6

bold_manual_panel <- bold_manual_plots$p_rain +
  labs(title = NULL)  # remove per-panel title

bold_auto_panel <- bold_auto_plots$p_rain +
  labs(title = NULL)  # remove per-panel title

bold_rain_combined <-
  (bold_manual_panel | bold_auto_panel) +
  plot_layout(
    widths = c(bold_manual_n, bold_auto_n),
    guides  = "collect"
  ) +
  plot_annotation(
    title    = "fMRI BOLD Image Qualtiy Metrics (IQMs)",
    subtitle = "A: low values excluded (SNR, tSNR)\nB: high values excluded (AOR, AQI, EFC, meanFD, DVARS, FWHM)",
    tag_levels = "A"
  ) &
  theme(
    legend.position      = "bottom",
    plot.title.position  = "plot",
    plot.title           = element_text(hjust = 0.5),
    plot.subtitle        = element_text(hjust = 0.5)
  )

bold_rain_combined

# ggsave("T1w_IQMs_rainclouds.pdf", t1_rain_combined,
#        width = 12, height = 6, units = "in", bg = "white", limitsize = FALSE)
# ggsave("BOLD_IQMs_rainclouds.pdf", bold_rain_combined,
#        width = 12, height = 6, units = "in", bg = "white", limitsize = FALSE)

library(dplyr)
library(tidyr)
library(readr)

id_cols <- c("participant_id", "ses_id")

# One row per subject/session across ALL sources
base_ids <- bind_rows(
  df_bold_auto_qc %>% select(all_of(id_cols)),
  df_bold_manual_qc %>% select(all_of(id_cols)),
  df_t1_auto_qc   %>% select(all_of(id_cols)),
  df_t1_manual_qc %>% select(all_of(id_cols))
) %>%
  distinct()

# Helper: keep first row if there are accidental duplicates
make_unique_by_id <- function(df) {
  df %>%
    arrange(across(all_of(id_cols))) %>%
    distinct(across(all_of(id_cols)), .keep_all = TRUE)
}

bold_auto_unique   <- make_unique_by_id(df_bold_auto_qc)
bold_manual_unique <- make_unique_by_id(df_bold_manual_qc)
t1_auto_unique     <- make_unique_by_id(df_t1_auto_qc)
t1_manual_unique   <- make_unique_by_id(df_t1_manual_qc)

# Drop any existing excluded_/qc_status_ when making metric blocks
bold_auto_metrics <- bold_auto_unique %>%
  select(-starts_with("excluded_"), -starts_with("qc_status_")) %>%
  rename_with(~ paste0("bold_auto_", .x), -all_of(id_cols))

bold_manual_metrics <- bold_manual_unique %>%
  select(-starts_with("excluded_"), -starts_with("qc_status_")) %>%
  rename_with(~ paste0("bold_manual_", .x), -all_of(id_cols))

t1_auto_metrics <- t1_auto_unique %>%
  select(-starts_with("excluded_"), -starts_with("qc_status_")) %>%
  rename_with(~ paste0("t1_auto_", .x), -all_of(id_cols))

t1_manual_metrics <- t1_manual_unique %>%
  select(-starts_with("excluded_"), -starts_with("qc_status_")) %>%
  rename_with(~ paste0("t1_manual_", .x), -all_of(id_cols))

# QC flag-only tables
bold_flags <- bold_auto_unique %>%
  select(all_of(id_cols), excluded_bold_auto) %>%
  full_join(
    bold_manual_unique %>%
      select(all_of(id_cols), excluded_bold_manual),
    by = id_cols
  )

t1_flags <- t1_auto_unique %>%
  select(all_of(id_cols), excluded_t1_auto) %>%
  full_join(
    t1_manual_unique %>%
      select(all_of(id_cols), excluded_t1_manual),
    by = id_cols
  )

# Combine all flags (one row per ID)
qc_flags_all <- base_ids %>%
  left_join(bold_flags, by = id_cols) %>%
  left_join(t1_flags,  by = id_cols) %>%
  mutate(
    across(starts_with("excluded_"), ~ tidyr::replace_na(.x, FALSE)),
    excluded_any = excluded_bold_auto |
      excluded_bold_manual |
      excluded_t1_auto    |
      excluded_t1_manual,
    qc_status_any = ifelse(excluded_any, "excluded", "included")
  )

# Now build the final wide metrics table (one row per subject/session)
all_IQMs_with_QC <- base_ids %>%
  left_join(bold_auto_metrics,   by = id_cols) %>%
  left_join(bold_manual_metrics, by = id_cols) %>%
  left_join(t1_auto_metrics,     by = id_cols) %>%
  left_join(t1_manual_metrics,   by = id_cols) %>%
  left_join(qc_flags_all,        by = id_cols)

all_IQMs_with_QC_clean <- all_IQMs_with_QC %>%
  tidyr::drop_na(
    -c(participant_id, ses_id)   # drop rows if ANY non-ID column has NA
  )

all_IQMs_with_QC_clean <- all_IQMs_with_QC_clean %>%
  dplyr::rename(
    sub = participant_id,
    ses = ses_id
  )

write_tsv(
  all_IQMs_with_QC_clean,
  "Desktop/ADNI_paper/temp/all_IQMs_with_QC_flags_clean.tsv"
)
