# =========================================================================
# ADNI MRIQC outlier detection: rainclouds + example (random +
# near-threshold) subject/session selection for supplemental QC figures.
#
# One unified pipeline. A single tail-aware threshold handles BOTH tails:
# tail = "upper" (flag high values, e.g. CJV/EFC/FWHM/AOR/AQI/meanFD/DVARS)
# or tail = "lower" (flag low values, e.g. CNR/SNR/TPM overlaps/tSNR).
#
# Sections:
#   1. Load data
#   2. compute_thresh()  -- tail-aware SHASH threshold (upper or lower)
#   3. prep_rain()       -- compute long data + per-session outlier flags
#                           (NO plot); plot_rain() -- draw the raincloud
#   4. add_qc_flags()    -- collapse per-session flags to per-subject QC
#   5. Metric sets (grouped by tail)
#   6. Prep all four groups, then build the modality-wide "outlier on ANY
#      metric" flags (T1w and BOLD separately)
#   7. Select example outliers (needs the fitted thresholds)
#   8. Draw the four panels (points colored by any-metric outlier status;
#      chosen examples highlighted) and combine into the two figures
#   9. Merge everything into one wide IQM + QC-flag table
#
# COLOR SCHEME on the rainclouds:
#   * grey  = within threshold for that metric
#   * red   = outlier for THAT metric (above/below its own threshold)
#   * blue  = one of the two chosen example sessions (random / near-
#             threshold) for that metric -- highlighted in its own panel
# =========================================================================

# ---- packages ----
library(tidyverse)     # dplyr, tidyr, ggplot2, purrr, readr, tibble, stringr
library(rrobot)        # SHASH_out(), normal_to_SHASH() -- robust outlier fit
library(ggrain)        # geom_rain() -- raincloud geometry
library(shadowtext)    # geom_shadowtext() -- readable labels over the cloud
library(patchwork)     # combine ggplots with | and plot_layout()

# Columns that uniquely identify one scan (one participant, one session).
id_cols <- c("participant_id", "ses_id")

# =========================================================================
# 1. Load data
# =========================================================================
# Wide MRIQC tables: one row per session, one column per IQM (plus id_cols).
df_bold <- readr::read_tsv("/Users/saigerutherford/Desktop/ADNI_paper/group_bold_full.tsv")
df_t1   <- readr::read_tsv("/Users/saigerutherford/Desktop/ADNI_paper/group_T1w_full.tsv")

names(df_bold)
names(df_t1)

# =========================================================================
# 2. Tail-aware threshold function
# =========================================================================
# Fit a Sinh-Arcsinh (SHASH) distribution to the finite values of x and
# return the value on the ORIGINAL data scale corresponding to the +/- 4
# standardized SHASH cut. rrobot handles the tail direction internally, so
# we forward `tail` to SHASH_out() and use z = +4 (upper) or -4 (lower).
compute_thresh <- function(x, tail = c("upper", "lower")) {
  tail <- match.arg(tail)
  x <- x[is.finite(x)]
  if (length(x) == 0) return(list(val = NA_real_, method = "NA"))

  fit <- SHASH_out(
    x,
    thr1     = 3,
    thr      = 4,
    tail     = tail,
    iso_seed = 123456
  )

  z_cut <- if (tail == "upper") 4 else -4
  out <- normal_to_SHASH(z_cut, fit$SHASH_coef$mu, fit$SHASH_coef$sigma,
                         fit$SHASH_coef$nu, fit$SHASH_coef$tau)

  list(val = out, method = "SHASH")
}

# =========================================================================
# 3. Raincloud: prep (data + flags) split from plot (drawing)
# =========================================================================
# prep_rain(): everything EXCEPT the ggplot. Returns the long data (with
# per-session is_outlier + facet labels), the per-metric thresholds, the
# metric list, and the tail. Splitting prep from plot keeps thresholds and
# example selection reusable without redrawing.
prep_rain <- function(df,
                      metrics,
                      tail    = c("upper", "lower"),
                      id_cols = c("participant_id", "ses_id")) {
  tail <- match.arg(tail)

  # (1) Long format: one row per (session x metric), ids preserved.
  df_long <- df %>%
    select(all_of(id_cols), all_of(metrics)) %>%
    pivot_longer(cols = all_of(metrics), names_to = "metric", values_to = "value")

  # (2) One threshold per metric, fit on the correct tail.
  thresholds <- purrr::map_dfr(
    metrics,
    \(nm) {
      res <- compute_thresh(df[[nm]], tail = tail)
      tibble(metric = nm, thresh_val = res$val, method = res$method)
    }
  )

  # (3) Flag outliers on the correct side (upper -> >, lower -> <).
  df_long2 <- df_long %>%
    left_join(thresholds, by = "metric") %>%
    mutate(
      is_outlier = dplyr::case_when(
        !is.finite(value) | !is.finite(thresh_val) ~ FALSE,
        tail == "upper" ~ value > thresh_val,
        tail == "lower" ~ value < thresh_val
      )
    )

  # Per-metric outlier counts, for the facet strip labels.
  outlier_stats <- df_long2 %>%
    group_by(metric) %>%
    summarize(
      n       = sum(is.finite(value)),
      n_out   = sum(is_outlier, na.rm = TRUE),
      pct_out = if_else(n > 0, 100 * n_out / n, NA_real_),
      .groups = "drop"
    )

  df_long2 <- df_long2 %>%
    left_join(outlier_stats, by = "metric") %>%
    mutate(metric_label = sprintf("%s\noutliers: %d (%.1f%%)", metric, n_out, pct_out))

  list(data = df_long2, thresholds = thresholds, metrics = metrics, direction = tail)
}

# plot_rain(): draw the faceted raincloud from a prep object.
#
#   prep        : output of prep_rain()
#   example_ids : OPTIONAL tibble(id_cols, metric[, ...]) -- these
#                 (session x metric) points are colored blue (the chosen
#                 random / near-threshold examples), in their own panel.
#   label_x     : x-position of the red threshold number. Raincloud lives
#                 around x = 1; bump this UP to push the label further right,
#                 away from the dots.
#
# Point coloring (per metric / per facet):
#   grey = within threshold for this metric
#   red  = outlier for THIS metric (above/below its own threshold)
#   blue = one of the two chosen example sessions for this metric
plot_rain <- function(prep,
                      example_ids   = NULL,
                      title_prefix  = "Dataset",
                      facet_cols    = 3,
                      label_x       = 1.55,
                      point_size    = 1.0,
                      id_cols       = c("participant_id", "ses_id")) {

  df_long2 <- prep$data

  # --- outlier status used for COLORING: this metric's own threshold ---
  df_long2 <- df_long2 %>% mutate(color_outlier = coalesce(is_outlier, FALSE))

  # --- mark the chosen example points (per metric) ---
  if (!is.null(example_ids) && nrow(example_ids) > 0) {
    ex <- example_ids %>%
      select(all_of(id_cols), metric) %>%
      distinct() %>%
      mutate(is_example = TRUE)
    df_long2 <- df_long2 %>%
      left_join(ex, by = c(id_cols, "metric")) %>%
      mutate(is_example = coalesce(is_example, FALSE))
  } else {
    df_long2 <- df_long2 %>% mutate(is_example = FALSE)
  }

  # --- one three-level class per point; order so examples/outliers draw last (on top) ---
  df_long2 <- df_long2 %>%
    mutate(point_class = factor(
      case_when(
        is_example    ~ "example",
        color_outlier ~ "outlier",
        TRUE          ~ "normal"
      ),
      levels = c("normal", "outlier", "example")
    )) %>%
    arrange(point_class)

  # One threshold row per facet for the dashed line + right-shifted label.
  ann <- df_long2 %>%
    distinct(metric_label, thresh_val) %>%
    filter(is.finite(thresh_val)) %>%
    mutate(label_x = label_x)

  ggplot(df_long2, aes(x = 1, y = value)) +
    # geom_rain's `cov` maps a column to the POINT color; violin/box keep
    # the fixed grey fill. Points are then styled by scale_colour_manual.
    geom_rain(fill = "grey85", alpha = 0.5,
              cov = "point_class",
              point.args = list(size = point_size, alpha = 0.8)) +
    scale_colour_manual(
      values = c(normal = "grey70", outlier = "red", example = "#1E90FF"),
      breaks = c("outlier", "example"),
      labels = c("Outlier (this metric)", "Chosen example"),
      name   = NULL,
      drop   = FALSE
    ) +
    geom_hline(
      data = ann,
      aes(yintercept = thresh_val),
      linetype = "dashed", color = "red", linewidth = 1
    ) +
    # Threshold number moved to the right (label_x) so it no longer sits
    # over the cloud/dots. hjust = 0 makes it grow rightward into the margin.
    shadowtext::geom_shadowtext(
      data = ann,
      aes(x = label_x, y = thresh_val, label = sprintf("%.3f", thresh_val)),
      hjust = 0, vjust = -0.4,
      color = "red", bg.color = "white",
      size = 4.2, fontface = "bold", bg.r = 0.15
    ) +
    facet_wrap(~ metric_label, scales = "free_y", ncol = facet_cols) +
    scale_y_continuous(expand = expansion(mult = c(0.05, 0.15))) +
    # extra room on the right for the moved label; clip = "off" so it isn't cut
    scale_x_continuous(expand = expansion(mult = c(0.05, 0.25))) +
    coord_cartesian(clip = "off") +
    labs(
      title = sprintf("%s \u2013 Rainclouds (%s tail)", title_prefix, prep$direction),
      y = "Value", x = NULL
    ) +
    theme_classic() +
    theme(
      axis.text.x  = element_blank(),
      axis.ticks.x = element_blank(),
      strip.text   = element_text(size = 6, lineheight = 0.9,
                                  margin = margin(t = 2, r = 2, b = 2, l = 2)),
      strip.background = element_rect(fill = "grey95", colour = NA),
      plot.margin  = margin(t = 35, r = 20, b = 10, l = 10),
      legend.position = "bottom"
    )
}

# =========================================================================
# 4. Per-session QC flags from a prep object
# =========================================================================
# Collapse per-session outlier flags into a per-session wide table of metric
# values plus one boolean excluded_<group> column (outlier on ANY of the
# group's metrics).
add_qc_flags <- function(prep, group_name, id_cols = c("participant_id", "ses_id")) {
  flag_col <- paste0("excluded_", group_name)

  per_session_flag <- prep$data %>%
    group_by(across(all_of(id_cols))) %>%
    summarize(!!flag_col := any(is_outlier, na.rm = TRUE), .groups = "drop")

  wide_metrics <- prep$data %>%
    select(all_of(id_cols), metric, value) %>%
    pivot_wider(names_from = metric, values_from = value)

  wide_metrics %>%
    left_join(per_session_flag, by = id_cols)
}

# =========================================================================
# 5. Metric sets, grouped by tail
# =========================================================================
## ---- T1w ----
t1_upper_metrics <- c("cjv_T1w", "efc_T1w", "fwhm_avg_T1w")                 # exclude HIGH
t1_lower_metrics <- c("cnr_T1w", "snr_total_T1w",
                      "tpm_overlap_csf_T1w", "tpm_overlap_gm_T1w", "tpm_overlap_wm_T1w")  # exclude LOW

## ---- BOLD ----
bold_upper_metrics <- c("aor", "aqi", "efc", "fd_mean", "dvars_std", "fwhm_avg")  # exclude HIGH
bold_lower_metrics <- c("snr", "tsnr")                                            # exclude LOW

# =========================================================================
# 6. Prep all four groups
# =========================================================================
t1_upper_prep   <- prep_rain(df_t1,   t1_upper_metrics,   tail = "upper")
t1_lower_prep   <- prep_rain(df_t1,   t1_lower_metrics,   tail = "lower")
bold_upper_prep <- prep_rain(df_bold, bold_upper_metrics, tail = "upper")
bold_lower_prep <- prep_rain(df_bold, bold_lower_metrics, tail = "lower")

# Per-session QC flag tables (unchanged downstream use).
t1_upper_qc   <- add_qc_flags(t1_upper_prep,   "t1_upper")
t1_lower_qc   <- add_qc_flags(t1_lower_prep,   "t1_lower")
bold_upper_qc <- add_qc_flags(bold_upper_prep, "bold_upper")
bold_lower_qc <- add_qc_flags(bold_lower_prep, "bold_lower")

# =========================================================================
# 7. Select TWO example outliers per metric: (a) random, (b) near-threshold
# =========================================================================
select_example_outliers <- function(df, metric_col, thresh_val, direction = c("upper", "lower"),
                                     id_cols = c("participant_id", "ses_id"),
                                     seed = 1) {
  direction <- match.arg(direction)
  set.seed(seed)

  d <- df %>%
    select(all_of(id_cols), value = all_of(metric_col)) %>%
    filter(is.finite(value))

  flagged <- if (direction == "upper") d %>% filter(value > thresh_val)
             else                      d %>% filter(value < thresh_val)

  if (nrow(flagged) == 0) {
    warning(sprintf("No outliers found for metric '%s' at threshold %.4f", metric_col, thresh_val))
    return(tibble())
  }

  random_pick <- flagged %>% slice_sample(n = 1) %>% mutate(example_type = "random")

  near_thresh_pick <- flagged %>%
    mutate(dist_to_thresh = abs(value - thresh_val)) %>%
    arrange(dist_to_thresh) %>%
    slice(1) %>%
    select(-dist_to_thresh) %>%
    mutate(example_type = "near_threshold")

  bind_rows(random_pick, near_thresh_pick) %>%
    mutate(metric = metric_col, thresh_val = thresh_val, direction = direction) %>%
    relocate(metric, direction, thresh_val, example_type, .after = all_of(id_cols[length(id_cols)]))
}

examples_for_group <- function(df, prep, id_cols = c("participant_id", "ses_id"), seed = 1) {
  purrr::pmap_dfr(
    prep$thresholds,
    \(metric, thresh_val, ...) select_example_outliers(
      df, metric_col = metric, thresh_val = thresh_val,
      direction = prep$direction, id_cols = id_cols, seed = seed
    )
  )
}

# Examples for each modality (used both for the CSV and for the blue
# highlight in the plots below).
t1_examples   <- bind_rows(examples_for_group(df_t1,   t1_upper_prep),
                           examples_for_group(df_t1,   t1_lower_prep))
bold_examples <- bind_rows(examples_for_group(df_bold, bold_upper_prep),
                           examples_for_group(df_bold, bold_lower_prep))

all_examples <- bind_rows(t1_examples, bold_examples)
print(all_examples, n = Inf)
write_csv(all_examples, "/Users/saigerutherford/Desktop/ADNI_paper/temp/supplemental_outlier_examples.csv")

# =========================================================================
# 8. Draw the four panels (per-metric red + example blue) and combine
# =========================================================================
# Points are red if they exceed that metric's own threshold; the two chosen
# example sessions per metric are highlighted blue in their own facet.
t1_upper_p <- plot_rain(t1_upper_prep,
                        example_ids = t1_examples, title_prefix = "T1w",
                        facet_cols = length(t1_upper_metrics))
t1_lower_p <- plot_rain(t1_lower_prep,
                        example_ids = t1_examples, title_prefix = "T1w",
                        facet_cols = length(t1_lower_metrics))
bold_upper_p <- plot_rain(bold_upper_prep,
                          example_ids = bold_examples, title_prefix = "BOLD",
                          facet_cols = length(bold_upper_metrics))
bold_lower_p <- plot_rain(bold_lower_prep,
                          example_ids = bold_examples, title_prefix = "BOLD",
                          facet_cols = length(bold_lower_metrics))

# Preview individual panels:
t1_upper_p
t1_lower_p
bold_upper_p
bold_lower_p

# ---- combine: lower panel on the left (tag A), upper on the right (tag B) ----
t1_upper_n <- length(t1_upper_metrics)
t1_lower_n <- length(t1_lower_metrics)

t1_rain_combined <-
  (t1_lower_p + labs(title = NULL) | t1_upper_p + labs(title = NULL)) +
  plot_layout(widths = c(t1_lower_n, t1_upper_n), guides = "collect") +
  plot_annotation(
    title    = "T1w Image Quality Metrics (IQMs)",
    subtitle = "A: low values excluded (CNR, SNR, TPM overlaps)\nB: high values excluded (CJV, EFC, FWHM)",
    tag_levels = "A"
  ) &
  theme(
    legend.position     = "bottom",
    plot.title.position = "plot",
    plot.title          = element_text(hjust = 0.5),
    plot.subtitle       = element_text(hjust = 0.5)
  )

t1_rain_combined

bold_upper_n <- length(bold_upper_metrics)
bold_lower_n <- length(bold_lower_metrics)

bold_rain_combined <-
  (bold_lower_p + labs(title = NULL) | bold_upper_p + labs(title = NULL)) +
  plot_layout(widths = c(bold_lower_n, bold_upper_n), guides = "collect") +
  plot_annotation(
    title    = "fMRI BOLD Image Quality Metrics (IQMs)",
    subtitle = "A: low values excluded (SNR, tSNR)\nB: high values excluded (AOR, AQI, EFC, meanFD, DVARS, FWHM)",
    tag_levels = "A"
  ) &
  theme(
    legend.position     = "bottom",
    plot.title.position = "plot",
    plot.title          = element_text(hjust = 0.5),
    plot.subtitle       = element_text(hjust = 0.5)
  )

bold_rain_combined

# ggsave("T1w_IQMs_rainclouds.pdf", t1_rain_combined,
#        width = 12, height = 6, units = "in", bg = "white", limitsize = FALSE)
# ggsave("BOLD_IQMs_rainclouds.pdf", bold_rain_combined,
#        width = 12, height = 6, units = "in", bg = "white", limitsize = FALSE)

# =========================================================================
# 9. Merge all per-session QC flags + metric values into one wide table
# =========================================================================
base_ids <- bind_rows(
  bold_upper_qc %>% select(all_of(id_cols)),
  bold_lower_qc %>% select(all_of(id_cols)),
  t1_upper_qc   %>% select(all_of(id_cols)),
  t1_lower_qc   %>% select(all_of(id_cols))
) %>%
  distinct()

rename_metrics <- function(df, prefix, id_cols) {
  df %>% rename_with(~ paste0(prefix, "_", .x), -all_of(c(id_cols, paste0("excluded_", prefix))))
}

bold_upper_named <- rename_metrics(bold_upper_qc, "bold_upper", id_cols)
bold_lower_named <- rename_metrics(bold_lower_qc, "bold_lower", id_cols)
t1_upper_named   <- rename_metrics(t1_upper_qc,   "t1_upper",   id_cols)
t1_lower_named   <- rename_metrics(t1_lower_qc,   "t1_lower",   id_cols)

all_IQMs_with_QC <- base_ids %>%
  left_join(bold_upper_named, by = id_cols) %>%
  left_join(bold_lower_named, by = id_cols) %>%
  left_join(t1_upper_named,   by = id_cols) %>%
  left_join(t1_lower_named,   by = id_cols) %>%
  mutate(
    across(starts_with("excluded_"), ~ tidyr::replace_na(.x, FALSE)),
    excluded_any  = excluded_bold_upper | excluded_bold_lower | excluded_t1_upper | excluded_t1_lower,
    qc_status_any = ifelse(excluded_any, "excluded", "included")
  )

all_IQMs_with_QC_clean <- all_IQMs_with_QC %>%
  tidyr::drop_na(-all_of(id_cols)) %>%
  dplyr::rename(sub = participant_id, ses = ses_id)

write_tsv(
  all_IQMs_with_QC_clean,
  "/Users/saigerutherford/Desktop/all_IQMs_with_QC_flags_clean.tsv"
)
