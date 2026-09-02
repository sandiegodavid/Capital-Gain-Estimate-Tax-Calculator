"""Chart construction for the Summary worksheet."""

from __future__ import annotations


def add_account_gain_chart(workbook, worksheet, last_account_row: int) -> None:
    """Add the short- and long-term gain comparison chart."""
    chart = workbook.add_chart({"type": "column"})
    for column in ("E", "F"):
        chart.add_series(
            {
                "name": f"='Summary'!${column}$9",
                "categories": f"='Summary'!$A$10:$A${last_account_row}",
                "values": f"='Summary'!${column}$10:${column}${last_account_row}",
            }
        )
    chart.set_title({"name": "Realized Gain by Account and Tax Term ($)"})
    chart.set_y_axis({"name": "Gain/Loss ($)"})
    chart.set_x_axis({"name": "Account"})
    chart.set_size({"width": 1080, "height": 540})
    worksheet.insert_chart("A15", chart)


def add_monthly_gain_chart(workbook, worksheet, final_month: int) -> None:
    """Add the monthly short- and long-term gain trend chart."""
    chart = workbook.add_chart({"type": "line"})
    last_month_row = 34 + final_month
    for column in ("B", "C"):
        chart.add_series(
            {
                "name": f"='Summary'!${column}$34",
                "categories": f"='Summary'!$A$35:$A${last_month_row}",
                "values": f"='Summary'!${column}$35:${column}${last_month_row}",
            }
        )
    chart.set_title({"name": "Monthly Realized Gain by Tax Term ($)"})
    chart.set_y_axis({"name": "Gain/Loss ($)"})
    chart.set_x_axis({"name": "Month"})
    chart.set_size({"width": 1080, "height": 540})
    worksheet.insert_chart("G15", chart)
