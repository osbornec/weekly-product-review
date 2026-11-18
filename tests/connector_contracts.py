"""Offline request models for the declared Drive and Workspace Sheets wrappers.

These adapters are development fixtures, not provider implementations. A real
connector must still pass authenticated execution and destination readback.
"""
import copy
import re


def coordinates(a1):
    match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", a1)
    if not match:
        raise ValueError("Expected bounded A1 range")

    def column(raw):
        total = 0
        for char in raw:
            total = total * 26 + ord(char) - 64
        return total - 1

    return int(match[2]) - 1, column(match[1]), int(match[4]), column(match[3]) + 1


def cell(value, column):
    if value == "" or value is None:
        return {}
    if isinstance(value, (int, float)):
        return {"numberValue": value}
    # Labels are always text. Payload formulas occupy value/analysis columns.
    return {"formulaValue" if str(value).startswith("=") and column >= 2 else "stringValue": str(value)}


def requests(plan, metadata, route):
    calls = []
    for tab in plan["tabs"]:
        live = metadata[tab["tab"]]
        if tab["expected_column"] and live["dates"].get(plan["date"]) != tab["expected_column"]:
            raise ValueError("Live date column differs; reconcile formula references before writing")
        for write in tab["writes"]:
            row, column, end_row, end_column = coordinates(write["range"])
            values = write["values"]
            if len(values) != end_row - row or any(len(line) != end_column - column for line in values):
                raise ValueError("The write must cover exactly its bounded range")
            if route == "drive":
                rows = [{"values": [{"userEnteredValue": cell(value, column + offset)} if cell(value, column + offset) else {}
                                    for offset, value in enumerate(line)]} for line in values]
                calls.append({"spreadsheet_id": "synthetic-sheet", "requests": [{"updateCells": {
                    "start": {"sheetId": live["sheet_id"], "rowIndex": row, "columnIndex": column},
                    "rows": rows, "fields": "userEnteredValue"}}]})
            elif route == "workspace":
                # The wrapper accepts string matrices. Separate RAW text from
                # USER_ENTERED numbers/formulas and use explicit clears.
                for r, line in enumerate(values):
                    for c, value in enumerate(line):
                        target = cell(value, column + c)
                        number = column + c + 1
                        letters = ""
                        while number:
                            number, remainder = divmod(number - 1, 26)
                            letters = chr(65 + remainder) + letters
                        address = letters + str(row + r + 1)
                        title = tab["tab"].replace("'", "''")
                        call = {"spreadsheet_id": "synthetic-sheet", "user_google_email": "synthetic@example.test",
                                "range_name": "'" + title + "'!" + address + ":" + address}
                        if not target:
                            call["clear_values"] = True
                        else:
                            kind, scalar = next(iter(target.items()))
                            call.update(values=[[str(scalar)]], value_input_option="RAW" if kind == "stringValue" else "USER_ENTERED")
                        calls.append(call)
            else:
                raise ValueError("Unknown offline connector route")
    return calls


def apply(initial, calls, route, metadata):
    """Small independent destination model; only cell values may change."""
    result = copy.deepcopy(initial)
    ids = {tab["sheet_id"]: title for title, tab in metadata.items()}

    def put(title, row, column, target):
        destination = result[title].setdefault((row, column), {})
        destination.pop("userEnteredValue", None)
        if target:
            destination["userEnteredValue"] = target

    for call in calls:
        if route == "drive":
            update = call["requests"][0]["updateCells"]
            if update["fields"] != "userEnteredValue":
                raise ValueError("Value writes cannot change notes or validation")
            start = update["start"]
            for r, line in enumerate(update["rows"]):
                for c, data in enumerate(line["values"]):
                    put(ids[start["sheetId"]], start["rowIndex"] + r, start["columnIndex"] + c, data.get("userEnteredValue"))
        else:
            title, address = call["range_name"].rsplit("!", 1)
            title = title[1:-1].replace("''", "'")
            row, column, _, _ = coordinates(address)
            if call.get("clear_values"):
                target = None
            else:
                value = call["values"][0][0]
                if call["value_input_option"] == "RAW":
                    target = {"stringValue": value}
                elif value.startswith("="):
                    target = {"formulaValue": value}
                else:
                    target = {"numberValue": float(value)}
            put(title, row, column, target)
    return result
