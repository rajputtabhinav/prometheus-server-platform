from __future__ import annotations

from app.models import AdvisoryInsight, AlertSeverity, MetricSnapshot, TaskRun


def build_node_advisories(metric: MetricSnapshot | None, recent_runs: list[TaskRun]) -> list[AdvisoryInsight]:
    advisories: list[AdvisoryInsight] = []
    if metric:
        if metric.cpu >= 90:
            advisories.append(
                AdvisoryInsight(
                    title="CPU pressure is high",
                    severity=AlertSeverity.CRITICAL,
                    summary=f"CPU is currently at {round(metric.cpu)}%, which is above the critical threshold.",
                    recommendation="Run cpu_test and inspect active workloads or hot processes on this node.",
                )
            )
        if metric.disk >= 90:
            advisories.append(
                AdvisoryInsight(
                    title="Disk saturation risk",
                    severity=AlertSeverity.WARNING,
                    summary=f"Disk pressure is at {round(metric.disk)}%, which may affect benchmark consistency.",
                    recommendation="Run disk_test and review storage queue depth and throughput behavior.",
                )
            )
        if (metric.temperature_c or 0) >= 85:
            advisories.append(
                AdvisoryInsight(
                    title="Thermal threshold crossed",
                    severity=AlertSeverity.CRITICAL,
                    summary=f"Temperature reached {round(metric.temperature_c or 0)}C on the latest snapshot.",
                    recommendation="Validate cooling and run a shorter verification workload before full stress tests.",
                )
            )

    failed_run = next((run for run in recent_runs if run.status == "failed"), None)
    if failed_run:
        advisories.append(
            AdvisoryInsight(
                title="Recent task failure needs review",
                severity=AlertSeverity.WARNING,
                summary=f"{failed_run.task} failed on this node during the latest execution window.",
                recommendation="Open the run details, inspect logs, and re-run the matching validation task after remediation.",
            )
        )

    if not advisories:
        advisories.append(
            AdvisoryInsight(
                title="Node is stable",
                severity=AlertSeverity.INFO,
                summary="No critical telemetry or recent execution failures are currently detected.",
                recommendation="Continue scheduled health sweeps and compare against the latest benchmark baseline.",
            )
        )
    return advisories[:4]


def build_run_advisories(run: TaskRun, previous_score: float | None) -> list[AdvisoryInsight]:
    advisories: list[AdvisoryInsight] = []
    if run.status == "failed":
        advisories.append(
            AdvisoryInsight(
                title="Execution failed",
                severity=AlertSeverity.CRITICAL,
                summary=run.error_message or "The run ended in a failed state.",
                recommendation="Inspect the logs and result payload, then retry only after the root cause is addressed.",
            )
        )
    if run.score is not None and previous_score is not None:
        delta = round(run.score - previous_score, 2)
        if delta <= -10:
            advisories.append(
                AdvisoryInsight(
                    title="Regression detected",
                    severity=AlertSeverity.WARNING,
                    summary=f"The latest score dropped by {abs(delta)} points compared with the previous comparable run.",
                    recommendation="Review hardware load, thermals, and recent changes before accepting this benchmark result.",
                )
            )
    if not advisories:
        advisories.append(
            AdvisoryInsight(
                title="Run looks healthy",
                severity=AlertSeverity.INFO,
                summary="No major regression or failure signal is detected for this run.",
                recommendation="Use this result as the current reference point for future comparisons.",
            )
        )
    return advisories[:3]
