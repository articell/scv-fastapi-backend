"""Testing Lab adapter using the production Python engine."""
from validation_engine import (
    CHECKS, CATALOGUE, IMPORT_REASON, LAYOUT48, ValidationError, evaluate,
    make_test_file, speech_marks_reason, trim,
)

FIRST = "Customer First Forename"
SURNAME = "Customer Surname or Company Name"


def run_lab(code, records, file, condition, lookup):
    if code == "DRAFT":
        field, op, value = condition.get("field"), condition.get("op"), condition.get("value", "")
        if field not in CATALOGUE["testFields"] or op not in {"blank", "equals", "contains"}:
            raise ValidationError("Choose a draft field and condition.")
        match = trim(value).lower()
        if op != "blank" and not match:
            raise ValidationError("Enter a match value for the draft condition.")
        findings = []
        for i, record in enumerate(records):
            source = trim(record.get(field, "")).lower()
            matched = not source if op == "blank" else source == match if op == "equals" else match in source
            if matched:
                findings.append({"id": record.get("SCVID") or f"Record {i + 1}", "field": field,
                                 "reason": "Draft condition matched in " + field + "."})
        return {"findings": findings, "records": len(records)}
    if code == "FAILED_IMPORT":
        try:
            return {"findings": [], "records": evaluate(file, [])["records"]}
        except ValidationError as error:
            if error.code != "FAILED_IMPORT":
                raise
            field = "Final line" if str(error) == IMPORT_REASON else "Quotation marks"
            return {"findings": [{"id": "File", "field": field, "reason": str(error)}], "records": 0}
    codes = [check[0] for check in CHECKS]
    if code not in codes:
        raise ValidationError("This check cannot run because its validation logic is unavailable.")
    if code == "FFSTP_5":
        if not records:
            raise ValidationError("The file has headings but no records.")
        findings = []
        for i, record in enumerate(records, 1):
            scvid = record.get("SCVID", "").strip(" ")
            if not scvid:
                raise ValidationError(f"Record {i} is missing an SCVID.")
            for field in LAYOUT48:
                value = record.get(field, "")
                reason = speech_marks_reason(value)
                if reason:
                    findings.append({"id": scvid, "field": field, "submittedValue": value, "reason": reason})
        return {"findings": findings, "records": len(records)}
    result = evaluate(make_test_file(records), [code], lookup)
    findings = []
    for row in result["results"][codes.index(code)]:
        scvid, cells = row["id"], row["cells"]
        if code in {"DQ_4", "DQ_24", "DQ_27", "FFSTP_4"}:
            findings.extend({"id": scvid, "field": cells[2][0], "reason": reason} for reason in cells[4])
        elif code == "FFSTP_6D":
            findings.append({"id": scvid, "field": "Aggregate Balance", "submittedValue": cells[2][0],
                             "expectedValue": cells[3][0], "difference": cells[4][0], "reason": cells[5][0]})
        elif code == "DQ_1":
            findings.append({"id": scvid, "field": cells[2][0], "reason": "Non-standard characters: " + ", ".join(cells[3])})
        elif code == "FFSTP_10":
            findings.extend({"id": scvid, "field": "Title", "reason": "Title is blank and Company Number is blank." if value == "[Blank]" else "Unrecognised title: " + value} for value in cells[2])
        elif code == "FFSTP_9":
            for reason in cells[2]:
                if reason.startswith("First Forename and"):
                    field = FIRST + ", " + SURNAME
                elif reason.startswith(("Surname is blank", "Surname contains")):
                    field = SURNAME
                elif reason.startswith("Surname is populated"):
                    field = FIRST + ", Company Number"
                elif reason.startswith("Numerical"):
                    fields = [FIRST, "Customer Second Forename", "Customer Third Forename", SURNAME]
                    field = ", ".join(name for name in fields if any(
                        trim(record.get("SCVID", "")) == scvid
                        and (name != SURNAME or not record.get("Company Number", "").strip(" "))
                        and any(char.isdecimal() for char in record.get(name, "")) for record in records))
                else:
                    field = FIRST
                findings.append({"id": scvid, "field": field, "reason": reason})
        elif code == "FFSTP_12":
            for reason in cells[3]:
                field = reason.removesuffix(" is missing") if reason.startswith("Address Line") else "Post Code"
                findings.append({"id": scvid, "field": field, "reason": reason})
        elif code == "FFSTP_2D":
            findings.extend({"id": scvid, "field": finding["field"], "reason": finding["reason"],
                             "reasonCode": finding["reasonCode"], "gradingEligible": finding["gradingEligible"]}
                            for finding in row["findings"])
    return {"findings": findings, "records": result["records"]}
