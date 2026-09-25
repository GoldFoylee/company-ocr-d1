"""Generate a formula-driven monthly vehicle billing workbook.

LOUD WARNING: the checked-in contract_rates.json contains fake placeholder rates and
vehicle metadata. Replace those values with approved contract data before production use.
Outstation and Night are intentionally blank because those amounts are manually judged.
"""

from __future__ import annotations

import argparse
import json
import re
from calendar import monthrange
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

DEFAULT_CONTRACT_RATES = Path(__file__).parents[2] / "config" / "contract_rates.json"
DETAIL_HEADERS = [
    "Sl. No.",
    "Veh.No",
    "Duty Date",
    "Days",
    "Modal",
    "St.Km",
    "Cl.Km",
    "Total Kms",
    "Start Time",
    "End Time",
    "Total Time",
    "Time Limit",
    "Extra Hrs",
    "Outstation",
    "Park/Toll",
    "Night",
]
RATE_KEYS = (
    "monthly_fare",
    "total_fix_km",
    "ex_km_rate",
    "ex_hr_rate",
    "outstation_rate",
    "night_rate",
)
_DURATION_RE = re.compile(
    r"^(?:(?P<days>\d+)d|(?P<hours>\d+(?:\.\d+)?)h|"
    r"(?P<clock>\d{1,3}:\d{2}(?::\d{2})?))$",
    re.I,
)


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_clock(value: Any) -> time:
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    parts = [int(part) for part in str(value).split(":")]
    if len(parts) == 2:
        return time(parts[0], parts[1])
    if len(parts) == 3:
        return time(parts[0], parts[1], parts[2])
    raise ValueError(f"Unsupported clock value: {value!r}")


def _duration_minutes(value: Any) -> int | None:
    """Convert known source duration text to minutes for Excel serial normalization."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return round(float(value) * 24 * 60)
    match = _DURATION_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"Unsupported source duration: {value!r}")
    if match.group("days") is not None:
        return int(match.group("days")) * 24 * 60
    if match.group("hours") is not None:
        return round(float(match.group("hours")) * 60)
    clock_parts = [int(part) for part in match.group("clock").split(":")]
    hours, minutes = clock_parts[:2]
    seconds = clock_parts[2] if len(clock_parts) == 3 else 0
    return hours * 60 + minutes + round(seconds / 60)


def _elapsed_datetimes(row: Mapping[str, Any], duty_date: date) -> tuple[datetime, datetime]:
    start_clock = _parse_clock(row["start_time"])
    end_clock = _parse_clock(row["close_time"])
    start_at = datetime.combine(duty_date, start_clock)
    # Time-of-day OCR omits elapsed day offsets. Ground-truth Total Time is only used to
    # preserve its whole-day offset; Excel still derives the precise elapsed value from
    # Start Time and End Time. This avoids trusting inconsistent rounded/handwritten totals.
    duration = _duration_minutes(row.get("total_time"))
    day_offset = duration // (24 * 60) if duration is not None else 0
    if end_clock < start_clock:
        day_offset = max(day_offset, 1)
    end_at = datetime.combine(duty_date + timedelta(days=day_offset), end_clock)
    return start_at, end_at


def _load_contract_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("vehicles"), dict):
        raise ValueError("Contract rates JSON must contain a 'vehicles' object")
    return config


def _vehicle_config(
    config: Mapping[str, Any], source: Mapping[str, Any]
) -> tuple[str, Mapping[str, Any]]:
    sheet_id = str(source["sheet_id"])
    vehicle_key = source.get("vehicle_no") or source.get("vehicle")
    if vehicle_key is None:
        vehicle_key = next(
            (
                row.get("vehicle_no") or row.get("vehicle")
                for row in source.get("rows", [])
                if row.get("vehicle_no") or row.get("vehicle")
            ),
            None,
        )
    if vehicle_key is None:
        vehicle_key = config.get("fixture_sheet_to_vehicle", {}).get(sheet_id)
    if vehicle_key is None:
        raise ValueError(
            f"Input {sheet_id!r} needs a vehicle_no or a fixture_sheet_to_vehicle config entry"
        )
    vehicle_key = str(vehicle_key)
    vehicles = config["vehicles"]
    if vehicle_key not in vehicles:
        raise ValueError(
            f"No vehicle contract config for {vehicle_key!r}; add it to contract_rates.json"
        )
    vehicle = vehicles[vehicle_key]
    missing = [key for key in RATE_KEYS if key not in vehicle.get("contract_rates", {})]
    if missing:
        raise ValueError(f"Missing contract rate(s) for {vehicle_key}: {', '.join(missing)}")
    return vehicle_key, vehicle


def _tab_title(value: str) -> str:
    title = re.sub(r"[\\/*?:\[\]]", "_", value).strip("'")
    return (title or "Vehicle")[:31]


def _set_formula(cell: Any, formula: str, number_format: str | None = None) -> None:
    cell.value = formula
    if number_format:
        cell.number_format = number_format


def _style_sheet(sheet: Any) -> None:
    thin_black = Side(style="thin", color="000000")
    for row in sheet.iter_rows(min_row=1, max_row=49, min_col=1, max_col=16):
        for cell in row:
            cell.font = Font(name="Arial", size=9, color="000000")
            cell.alignment = Alignment(vertical="center")
            cell.border = Border()

    sheet["A1"].font = Font(name="Arial", size=14, bold=True, color="000000")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet["A2"].font = Font(name="Arial", size=9, bold=True)
    for cell in sheet[3]:
        cell.font = Font(name="Arial", size=9, bold=True, color="000000")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(top=thin_black, bottom=thin_black, left=thin_black, right=thin_black)

    for row_number in (36, 37, 38, 39, 41, 48):
        for cell in sheet[row_number]:
            if cell.value is not None:
                cell.font = Font(name="Arial", size=9, bold=True)
    for row_number in range(4, 35):
        for column in range(1, 17):
            sheet.cell(row_number, column).border = Border(
                top=thin_black, bottom=thin_black, left=thin_black, right=thin_black
            )
    for row_number in range(36, 40):
        for column in range(6, 11):
            sheet.cell(row_number, column).border = Border(
                top=thin_black, bottom=thin_black, left=thin_black, right=thin_black
            )

    for row_number in range(42, 48):
        for column in range(6, 13):
            sheet.cell(row_number, column).border = Border(
                bottom=thin_black, left=thin_black, right=thin_black
            )
    for cell in sheet[48]:
        if cell.column in range(6, 13):
            cell.border = Border(
                top=thin_black,
                bottom=thin_black,
                left=thin_black,
                right=thin_black,
            )

    sheet.merge_cells("A1:P1")
    sheet.merge_cells("A2:P2")
    for row_number in range(4, 35):
        sheet[f"C{row_number}"].number_format = "d-mmm-yy"
        for column in (6, 7, 8, 15):
            sheet.cell(row_number, column).number_format = "#,##0.##"
        for column in (9, 10, 12):
            sheet.cell(row_number, column).number_format = "h:mm"
        for column in (11, 13):
            sheet.cell(row_number, column).number_format = "[h]:mm"
    numeric_cells = (
        "J37",
        "J38",
        "J39",
        "J42",
        "K42",
        "L42",
        "J43",
        "K43",
        "L43",
        "J44",
        "K44",
        "L44",
        "J45",
        "K45",
        "L45",
        "J46",
        "K46",
        "L46",
        "J47",
        "K47",
        "L47",
        "L48",
    )
    for coordinate in numeric_cells:
        sheet[coordinate].number_format = "#,##0.00"

    widths = [8, 12, 13, 13, 12, 11, 11, 12, 12, 12, 12, 12, 11, 13, 13, 10]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[1].height = 22
    sheet.row_dimensions[2].height = 20
    sheet.row_dimensions[3].height = 34
    sheet.freeze_panes = "A4"
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_area = "A1:P51"


def _build_vehicle_sheet(
    workbook: Workbook,
    source: Mapping[str, Any],
    config: Mapping[str, Any],
) -> str:
    vehicle_key, vehicle = _vehicle_config(config, source)
    rows = source["rows"]
    contracts = vehicle["contract_rates"]
    dates = [_parse_date(row["date"]) for row in rows]
    if not dates:
        raise ValueError(f"No rows provided for {vehicle_key!r}")
    periods = {(value.year, value.month) for value in dates}
    if len(periods) != 1:
        raise ValueError(f"All rows for {vehicle_key!r} must belong to one calendar month")
    year, month = next(iter(periods))
    rows_by_day: dict[int, Mapping[str, Any]] = {}
    for row, duty_date in zip(rows, dates, strict=True):
        if duty_date.day in rows_by_day:
            raise ValueError(
                f"Multiple duty rows on {duty_date} are unsupported by this report layout"
            )
        rows_by_day[duty_date.day] = row

    vehicle_no = str(vehicle.get("vehicle_no", vehicle_key))
    sheet = workbook.create_sheet(title=_tab_title(vehicle_no))
    last_day = monthrange(year, month)[1]
    sheet["A1"] = "BILL DETAIL REPORT"
    sheet["A2"] = (
        f"Client Name :- {vehicle.get('client_name') or 'PLACEHOLDER'}    "
        f"Date :- 01/{month:02d}/{year}  To  {last_day:02d}/{month:02d}/{year}"
    )
    for column, header in enumerate(DETAIL_HEADERS, start=1):
        sheet.cell(row=3, column=column, value=header)

    for day in range(1, last_day + 1):
        row_number = 3 + day
        duty_date = date(year, month, day)
        row_data = rows_by_day.get(day)
        sheet.cell(row_number, 1, day)
        sheet.cell(row_number, 2, vehicle_no)
        sheet.cell(row_number, 3, datetime.combine(duty_date, time.min))
        _set_formula(sheet.cell(row_number, 4), f'=UPPER(TEXT(C{row_number},"dddd"))')
        sheet.cell(row_number, 5, vehicle.get("modal", ""))
        if row_data is None:
            continue

        start_value = row_data.get("start_km")
        close_value = row_data.get("close_km")
        if start_value is not None:
            sheet.cell(row_number, 6, start_value)
        if close_value is not None:
            sheet.cell(row_number, 7, close_value)
        _set_formula(sheet.cell(row_number, 8), f"=G{row_number}-F{row_number}", "0")

        start_at, end_at = _elapsed_datetimes(row_data, duty_date)
        sheet.cell(row_number, 9, start_at)
        sheet.cell(row_number, 10, end_at)
        _set_formula(sheet.cell(row_number, 11), f"=J{row_number}-I{row_number}", "[h]:mm")

        # Time limits are not present in the ground-truth log. A blank limit must not
        # be treated as zero; leave overtime at zero until a real value is configured.
        time_limit_hours = vehicle.get("time_limit_hours")
        if time_limit_hours is not None:
            sheet.cell(row_number, 12, float(time_limit_hours) / 24)
        _set_formula(
            sheet.cell(row_number, 13),
            f'=IF(L{row_number}="",0,MAX(0,K{row_number}-L{row_number}))',
            "[h]:mm",
        )

        # These fields are deliberately blank for manual entry. No derivation rule exists.
        sheet.cell(row_number, 14, None)
        toll = row_data.get("toll")
        parking = row_data.get("parking")
        if toll is not None or parking is not None:
            sheet.cell(row_number, 15, (toll or 0) + (parking or 0))
        sheet.cell(row_number, 16, None)

    # Daily summary and billing layout follow the inspected account workbooks.
    sheet["F36"] = "Total"
    _set_formula(sheet["H36"], "=SUM(H4:H34)", "#,##0")
    _set_formula(sheet["K36"], "=SUM(K4:K34)", "[h]:mm")
    _set_formula(sheet["M36"], "=SUM(M4:M34)", "[h]:mm")
    _set_formula(sheet["O36"], "=SUM(O4:O34)", "#,##0.00")
    sheet["F37"] = "Total Fix Km"
    sheet["J37"] = contracts["total_fix_km"]
    sheet["F38"] = "Cab Run"
    _set_formula(sheet["J38"], "=H36", "#,##0")
    sheet["F39"] = "Total Working Days"
    _set_formula(sheet["J39"], "=COUNTIF(H4:H34,\">0\")", "0")

    for column, header in ((6, "Particulars"), (10, "QTY"), (11, "Rate"), (12, "Amt")):
        sheet.cell(41, column, header)
    for row_number in range(41, 49):
        sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=9)
    billing_labels = {
        42: "Monthly Fare",
        43: "Ex-Kms",
        44: "Ex-Hrs.",
        45: "TOLL TAX",
        46: "Outstation",
        47: "Night Charges",
        48: "Total Amt.=",
    }
    for row_number, label in billing_labels.items():
        sheet.cell(row_number, 6, label)
    sheet["J42"] = 1
    sheet["K42"] = contracts["monthly_fare"]
    _set_formula(sheet["L42"], "=J42*K42", "#,##0.00")
    _set_formula(sheet["J43"], "=MAX(0,J38-J37)", "#,##0")
    sheet["K43"] = contracts["ex_km_rate"]
    _set_formula(sheet["L43"], "=J43*K43", "#,##0.00")
    _set_formula(sheet["J44"], "=M36", "[h]:mm")
    sheet["K44"] = contracts["ex_hr_rate"]
    _set_formula(sheet["L44"], "=J44*K44", "#,##0.00")
    sheet["J45"] = 1
    _set_formula(sheet["K45"], "=O36", "#,##0.00")
    _set_formula(sheet["L45"], "=J45*K45", "#,##0.00")
    # Manual-only totals remain empty until an authorized human enters quantities.
    sheet["K46"] = contracts["outstation_rate"]
    _set_formula(sheet["L46"], '=IF(J46="","",J46*K46)', "#,##0.00")
    sheet["K47"] = contracts["night_rate"]
    _set_formula(sheet["L47"], '=IF(J47="","",J47*K47)', "#,##0.00")
    _set_formula(sheet["L48"], "=SUM(L42:L47)", "#,##0.00")

    if vehicle.get("placeholder_rates", True):
        sheet.merge_cells("A51:P51")
        sheet["A51"] = (
            "PLACEHOLDER CONTRACT RATES AND VEHICLE METADATA — "
            "REPLACE WITH APPROVED REAL VALUES BEFORE PRODUCTION USE"
        )
        sheet["A51"].font = Font(name="Arial", size=10, bold=True, color="9C0006")
        sheet["A51"].fill = PatternFill("solid", fgColor="FFC7CE")
        sheet["A51"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.row_dimensions[51].height = 28
    _style_sheet(sheet)
    return vehicle_key


def create_monthly_billing_export(
    inputs: Iterable[Path | str | Mapping[str, Any]],
    output_path: Path | str,
    contract_rates_path: Path | str = DEFAULT_CONTRACT_RATES,
) -> Path:
    """Create one bill-detail worksheet per vehicle from OCR/ground-truth sheet JSON."""
    config_path = Path(contract_rates_path)
    config = _load_contract_config(config_path)
    sheets: list[Mapping[str, Any]] = []
    for item in inputs:
        if isinstance(item, Mapping):
            sheets.append(item)
        else:
            sheets.append(json.loads(Path(item).read_text(encoding="utf-8")))
    if not sheets:
        raise ValueError("At least one vehicle sheet input is required")
    months = {
        (_parse_date(row["date"]).year, _parse_date(row["date"]).month)
        for source in sheets
        for row in source["rows"]
    }
    if len(months) != 1:
        raise ValueError("All vehicle inputs in one workbook must belong to the same month")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    seen_ids: set[str] = set()
    seen_vehicle_keys: set[str] = set()
    for source in sheets:
        sheet_id = str(source["sheet_id"])
        if sheet_id in seen_ids:
            raise ValueError(f"Duplicate sheet_id {sheet_id!r}")
        seen_ids.add(sheet_id)
        vehicle_key, _ = _vehicle_config(config, source)
        if vehicle_key in seen_vehicle_keys:
            raise ValueError(f"Duplicate vehicle {vehicle_key!r} in monthly inputs")
        seen_vehicle_keys.add(vehicle_key)
        _build_vehicle_sheet(workbook, source, config)
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"
    workbook.save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="one JSON ground-truth/extraction file per vehicle",
    )
    parser.add_argument("--output", type=Path, required=True, help="destination .xlsx file")
    parser.add_argument(
        "--contract-rates",
        type=Path,
        default=DEFAULT_CONTRACT_RATES,
        help="per-vehicle configuration JSON (defaults to config/contract_rates.json)",
    )
    args = parser.parse_args()
    path = create_monthly_billing_export(args.inputs, args.output, args.contract_rates)
    print(path)


if __name__ == "__main__":
    main()
