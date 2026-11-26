"""SCV parsing and validation shared by submissions and the Testing Lab."""
from decimal import Decimal, localcontext
import json
from pathlib import Path
import re
import unicodedata

CATALOGUE = json.loads((Path(__file__).parent / "catalogue.json").read_text(encoding="utf-8"))
CHECKS = CATALOGUE["checks"]
LAYOUT51 = CATALOGUE["layout51"]
REPEATED = (13, 26, 48)
LAYOUT48 = [field for i, field in enumerate(LAYOUT51) if i not in REPEATED]
FIELD_MAX_LENGTHS = CATALOGUE["fieldMaxLengths"]
LENGTH_CHECK = next(i for i, check in enumerate(CHECKS) if check[0] == "FFSTP_4")
DEPOSIT_CHECK = next(i for i, check in enumerate(CHECKS) if check[0] == "DQ_4")
SPEECH_MARKS_CHECK = next(i for i, check in enumerate(CHECKS) if check[0] == "FFSTP_5")
AGGREGATE_CHECK = next(i for i, check in enumerate(CHECKS) if check[0] == "FFSTP_6D")
GRADING_CHECKS = {i for i, (code, _, _) in enumerate(CHECKS) if code.startswith("FFSTP_") or code == "DQ_34"}
MARKER = "9" * 20
IMPORT_REASON = "Invalid or missing end-of-file marker. Every SCV file must end with exactly twenty consecutive 9s on the final line."
GENERIC = "Please update the missing/incorrectly populated name detail(s) based on whether is an individual or non-personal record"
COMPANY = "Please check if this is a company and update the missing/incorrectly populated name detail(s) based on whether it is an individual or non-personal record"
TITLE_ACTION = "Please confirm whether the Title would be suitable to be used in correspondence and in the payee name for a cheque payment."
NUMERIC = "Numerical characters are found in the name fields for potential individuals. Please check if they are individuals or companies and correct the record accordingly."
PERSONAL_REASON = "First forename is blank. The depositor may potentially be an individual based on other personal fields being populated (Customer 2nd forename, Customer 3rd forename, Date of Birth or NI Number)"
TRIM = "\u0009\u000a\u000b\u000c\u000d \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
UK = re.compile(r"^(?:UK|GB|GBR|U\.?K\.?|UNITED KINGDOM|GREAT BRITAIN|ENGLAND|SCOTLAND|WALES|NORTHERN IRELAND)$", re.I | re.ASCII)
POSTCODE = re.compile(r"^(?:GIR ?0AA|(?:[A-PR-UWYZ][0-9](?:[0-9]|[A-HJKPSTUW])?|[A-PR-UWYZ][A-HK-Y][0-9](?:[0-9]|[ABEHMNPRVWXY])?) ?[0-9][ABD-HJLNP-UW-Z]{2})$")
BFPO_POSTCODE = re.compile(r"BF1 ?[0-9][ABD-HJLNP-UW-Z]{2}")
BFPO_REFERENCE = json.loads(Path(__file__).with_name("bfpo_reference.json").read_text(encoding="utf-8"))
BFPO_KEYS = frozenset(postcode.upper().replace(" ", "") for postcode in BFPO_REFERENCE["postcodes"])
SPACE = "[" + re.escape(TRIM) + "-]+"
PHRASES = ["NO FIXED ADDRESS", "NAME NOT KNOWN", "ADDRESS UNKNOWN", "INVALID ADDRESS",
           "BAD ADDRESS", "NAME UNKNOWN", "NOT PROVIDED", "NO ADDRESS", "NOT KNOWN", "UNKNOWN"]
TIER_ONE = re.compile("|".join(SPACE.join(phrase.split()) for phrase in PHRASES), re.I)
COMMENTS = re.compile(SPACE.join(["HOLD", "MAIL"]) + "|" + SPACE.join(["GONE", "AWAY"]), re.I)
TIER_TWO = re.compile(r"^(?:N/A|NONE|NFA|TBC|TBA|TBD|NULL)$", re.I | re.ASCII)
NAME_FIELDS = {"Customer First Forename", "Customer Second Forename", "Customer Third Forename",
               "Customer Surname or Company Name", "Previous Name"}
CONTROLS = {0: "NUL", 9: "Tab", 10: "LF", 13: "CR", 160: "Non-breaking space", 8203: "Zero-width space", 65279: "BOM"}


class ValidationError(ValueError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def trim(value):
    return value.strip(TRIM)


def blank(value):
    return not value.strip(" ")


def title_key(value):
    return value.strip(" ").replace(".", "").lower()


TITLES = {title_key(value) for value in CATALOGUE["titles"]}


def speech_marks_reason(submitted_value):
    if any(mark in submitted_value for mark in ('"', "\u201c", "\u201d")):
        return "Speech marks were found."
    return None


def parse(source, delimiter, *, submitted_rows=None):
    rows, row, field = [], [], []
    submitted_row, field_start = [], 0
    quoted = closed = False
    i = 0
    while i < len(source):
        char = source[i]
        if quoted:
            if char != '"':
                field.append(char)
            elif i + 1 < len(source) and source[i + 1] == '"':
                field.append('"')
                i += 1
            else:
                quoted, closed = False, True
        elif char == delimiter or char in "\r\n":
            row.append("".join(field))
            if submitted_rows is not None:
                submitted_row.append(source[field_start:i])
            field, closed = [], False
            if char in "\r\n":
                if char == "\r" and i + 1 < len(source) and source[i + 1] == "\n":
                    i += 1
                if len(row) > 1 or row[0]:
                    rows.append(row)
                    if submitted_rows is not None:
                        submitted_rows.append(submitted_row)
                row, submitted_row = [], []
            field_start = i + 1
        elif closed:
            raise ValidationError(
                f"Invalid quotation marks in row {len(rows) + 1}, column {len(row) + 1}: "
                "unexpected text after the closing double quotation mark.", "FAILED_IMPORT")
        elif char == '"' and not field:
            quoted = True
        else:
            field.append(char)
        i += 1
    if quoted:
        raise ValidationError(
            f"Invalid quotation marks in row {len(rows) + 1}, column {len(row) + 1}: "
            "the opening double quotation mark was not closed.", "FAILED_IMPORT")
    row.append("".join(field))
    if len(row) > 1 or row[0]:
        rows.append(row)
        if submitted_rows is not None:
            submitted_rows.append([*submitted_row, source[field_start:]])
    return rows


def parse_file(source, *, submitted_rows=None):
    source = source.removeprefix("\ufeff")
    file = re.sub(r"\r?\n\Z", "", source)
    boundary = file.rfind("\n")
    records_text = file[:boundary + 1] if boundary >= 0 else ""
    if file[boundary + 1:] != MARKER or re.search(r"(?:^|\n)9{20}\r?\n", records_text):
        raise ValidationError(IMPORT_REASON, "FAILED_IMPORT")
    header = re.split(r"\r\n|\n|\r", records_text, maxsplit=1)[0]
    separator, width = ",", 0
    for candidate in (",", "|", ";"):
        try:
            parsed = parse(header, candidate)
            candidate_width = len(parsed[0]) if parsed else 0
            if candidate_width > width:
                separator, width = candidate, candidate_width
        except ValidationError:
            pass
    parsed = parse(records_text, separator, submitted_rows=submitted_rows)
    if not parsed:
        raise ValidationError("The file is empty.")
    headers, records = parsed[0], parsed[1:]
    if len(headers) not in (48, 51):
        raise ValidationError(f"SCV files must have 48 columns or 51 columns for the repeated SCVID layout. This file has {len(headers)} columns.")
    layout = LAYOUT51 if len(headers) == 51 else LAYOUT48
    for i, expected in enumerate(layout):
        if headers[i] != expected:
            raise ValidationError(f'Column {i + 1} must be headed "{expected}". Check the SCV column order.')
    if not records:
        raise ValidationError("The file has headings but no records.")
    return headers, records


def decode_upload(data):
    try:
        return {"source": data.decode("utf-8-sig"), "legacy": False}
    except UnicodeDecodeError:
        # WHATWG windows-1252 preserves undefined bytes as their C1 codepoints.
        source = "".join(bytes([byte]).decode("cp1252", errors="replace") if byte not in {129, 141, 143, 144, 157}
                         else chr(byte) for byte in data)
        try:
            evaluate(source, [])
        except ValidationError as error:
            if error.code == "FAILED_IMPORT":
                raise
            raise ValidationError("This file could not be read as UTF-8 or recognised as a Windows-1252 SCV file. Save a copy as UTF-8 and try again.") from None
        return {"source": source, "legacy": True}


def word_matches(pattern, value):
    def letter_number(char):
        return unicodedata.category(char)[0] in "LN"
    return [match[0].upper() for match in pattern.finditer(value)
            if (match.start() == 0 or not letter_number(value[match.start() - 1]))
            and (match.end() == len(value) or not letter_number(value[match.end()]))]


def keywords(value, contextual):
    matches = word_matches(TIER_ONE, value)
    if contextual and TIER_TWO.fullmatch(trim(value)):
        matches.append(trim(value).upper())
    return matches


def invalid_label(char):
    code = ord(char)
    if code < 32 or 128 <= code <= 159 or unicodedata.category(char) in {"Cc", "Cf", "Zs", "Zl", "Zp"}:
        return f"[{CONTROLS.get(code, 'Invisible character')} — code {code}]"
    return char


FIRST = "Customer First Forename"
SURNAME = "Customer Surname or Company Name"
PENNY_AMOUNT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]{1,2})?|\.[0-9]{1,2})")
SORT_CODE_FORMAT = re.compile(r"[0-9]{6}|[0-9]{2}([ -])[0-9]{2}\1[0-9]{2}")
COMPLETE_IBAN = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
BIC_FORMAT = re.compile(r"[A-Z0-9]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")
IBAN_LENGTHS = CATALOGUE["ibanReference"]["lengths"]
REPEATED_ACCOUNT_REASON = "Aggregate Balance could not be verified because repeated customer/account rows require review."


def penny_amount(value):
    amount = trim(value)
    return Decimal(amount) if PENNY_AMOUNT.fullmatch(amount) else None


def valid_iban(iban):
    if not COMPLETE_IBAN.fullmatch(iban) or len(iban) != IBAN_LENGTHS.get(iban[:2]):
        return False
    if not 2 <= int(iban[2:4]) <= 98:
        return False
    # ISO IBAN checksum: move country and check digits to the end, then expand letters.
    reordered = iban[4:] + iban[:4]
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in reordered)
    return int(digits) % 97 == 1


def account_identifiers(sort_code, account_number, iban, bic):
    sort_code, account_number = trim(sort_code), trim(account_number)
    malformed = []
    if sort_code:
        if not SORT_CODE_FORMAT.fullmatch(sort_code):
            malformed.append("Sort Code")
        elif account_number:
            return ("sort", re.sub(r"[ -]", "", sort_code), account_number), malformed
    iban = trim(iban).replace(" ", "")
    if iban:
        if iban.isascii() and valid_iban(iban.upper()):
            return ("iban", iban.upper()), malformed
        malformed.append("IBAN")
    bic = trim(bic)
    if bic:
        if not (bic.isascii() and BIC_FORMAT.fullmatch(bic.upper())):
            malformed.append("BIC")
        elif account_number:
            return ("bic", bic.upper(), account_number), malformed
    return None, malformed


def aggregate_findings(records, index, row_indices):
    entries = []
    seen_accounts = set()
    repeated = False
    for row_index in row_indices:
        record = records[row_index]
        get = lambda field: record[index[field]]
        identity, malformed = account_identifiers(get("Sort Code"), get("Account Number"), get("IBAN"), get("BIC"))
        submitted = get("Aggregate Balance")
        for field in malformed:
            yield row_index, submitted, "", "", f"{field} is malformed; please review the account identifier.", False
        if identity is not None:
            repeated |= identity in seen_accounts
            seen_accounts.add(identity)
        entries.append((row_index, get("Account Balance in Sterling"), submitted))

    amounts = [penny_amount(sterling) for _, sterling, _ in entries]
    if repeated or any(amount is None for amount in amounts):
        reason = REPEATED_ACCOUNT_REASON if repeated else (
            "Aggregate Balance could not be verified because an Account Balance in Sterling is blank or invalid.")
        for row_index, _, submitted in entries:
            yield row_index, submitted, "", "", reason, False
        return

    # Include enough digits for the largest input and any carry from summing the group.
    with localcontext() as context:
        max_input_length = max(len(value) for _, sterling, submitted in entries for value in (sterling, submitted))
        context.prec = max_input_length + len(str(len(entries))) + 4
        expected = sum((amount for amount in amounts if amount > 0), Decimal(0))
        expected_text = f"{expected:.2f}"
        for row_index, _, submitted in entries:
            actual = penny_amount(submitted)
            if actual is None:
                yield (row_index, submitted, expected_text, "",
                       "Aggregate Balance could not be verified because the submitted Aggregate Balance is blank or invalid.", False)
            elif actual != expected:
                yield (row_index, submitted, expected_text, f"{abs(actual - expected):.2f}",
                       "Submitted Aggregate Balance differs from the sum of positive Account Balances in Sterling.", True)


def evaluate(source, selected=None, lookup=None):
    selected = [check[0] for check in CHECKS] if selected is None else selected
    if any(code not in {check[0] for check in CHECKS} for code in selected):
        raise ValidationError("An unavailable validation check was selected.")
    enabled = [check[0] in selected for check in CHECKS]
    submitted_rows = [] if enabled[SPEECH_MARKS_CHECK] else None
    headers, records = parse_file(source, submitted_rows=submitted_rows)
    index = {heading: headers.index(heading) for heading in headers}
    buckets = [{} for _ in CHECKS]
    affected_records = [set() for _ in CHECKS]
    grading_affected_records = [set() for _ in CHECKS]
    ids, affected = set(), set()
    grading_affected = set()
    postcode_rows = {}
    aggregate_rows = {}

    def flag(check, record_index, scvid, group, cells, fields=(), grading_eligible=True):
        affected_records[check].add(record_index)
        if grading_eligible and check in GRADING_CHECKS:
            grading_affected_records[check].add(record_index)
            grading_affected.add(scvid)
        key = json.dumps([scvid, group], ensure_ascii=False)
        if key not in buckets[check]:
            buckets[check][key] = {"id": scvid, "cells": [[] for _ in cells]}
        if fields:
            affected_fields = buckets[check][key].setdefault("fields", [])
            submitted_values = buckets[check][key].setdefault("submittedValues", {})
            for field in fields:
                if field not in affected_fields:
                    affected_fields.append(field)
                value = records[record_index][index[field]]
                display_value = value if trim(value) else "[BLANK]"
                values = submitted_values.setdefault(field, [])
                if display_value not in values:
                    values.append(display_value)
        for previous, values in zip(buckets[check][key]["cells"], cells):
            for value in values:
                if value not in previous:
                    previous.append(value)
        affected.add(scvid)
        return buckets[check][key]

    for record_index, record in enumerate(records):
        if len(record) != len(headers):
            raise ValidationError(f"Record {record_index + 1} has {len(record)} fields. Expected {len(headers)}.")
        get = lambda heading: record[index[heading]]
        raw_id = get("SCVID")
        scvid = raw_id.strip(" ")
        if not scvid:
            raise ValidationError(f"Record {record_index + 1} is missing an SCVID.")
        if len(headers) == 51 and any(record[i] != raw_id for i in REPEATED):
            raise ValidationError(f"Record {record_index + 1} has inconsistent repeated SCVID values.")
        ids.add(scvid)
        if enabled[AGGREGATE_CHECK]:
            aggregate_rows.setdefault(scvid, []).append(record_index)
        status, title = get("Account Status Code"), get("Title")
        first, second, third, surname = [get(field) for field in [
            "Customer First Forename", "Customer Second Forename", "Customer Third Forename", "Customer Surname or Company Name"]]
        dob, ni, number = get("Customer Date of Birth"), get("National Insurance Number"), get("Company Number")
        if enabled[0]:
            findings = []
            for label in ("Aggregate Balance", "Compensatable Amount"):
                value = get(label)
                if blank(value):
                    reason_code = "missing"
                elif not re.fullmatch(r" *[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+) *", value):
                    continue
                else:
                    if not re.search("[1-9]", value):
                        reason_code = "zero"
                    elif value.lstrip(TRIM).startswith("-"):
                        reason_code = "negative"
                    else:
                        continue
                reason = label + " is " + reason_code
                if reason_code == "zero":
                    reason += "—reported for review; may be valid"
                findings.append({"field": label, "reasonCode": reason_code, "reason": reason,
                                 "gradingEligible": reason_code in {"missing", "negative"},
                                 "accountStatusCodes": [status],
                                 "submittedValues": [value if reason_code != "missing" else "[BLANK]"]})
            if findings:
                row = flag(0, record_index, scvid, "", [[scvid], [f["reason"] for f in findings]],
                           grading_eligible=any(f["gradingEligible"] for f in findings))
                grouped = row.setdefault("findings", [])
                for finding in findings:
                    existing = next((item for item in grouped if
                                     (item["field"], item["reasonCode"]) ==
                                     (finding["field"], finding["reasonCode"])), None)
                    if existing is None:
                        grouped.append(finding)
                        continue
                    for key in ("accountStatusCodes", "submittedValues"):
                        value = finding[key][0]
                        if value not in existing[key]:
                            existing[key].append(value)
        if enabled[1]:
            reasons, actions, fields = [], [], []

            def name_failure(reason, affected_fields, action=GENERIC):
                reasons.append(reason)
                actions.append(action)
                fields.extend(affected_fields)

            if blank(surname):
                if blank(first):
                    name_failure("First Forename and Surname are blank", [FIRST, SURNAME])
                else:
                    name_failure("Surname is blank", [SURNAME])
            elif blank(first):
                if any(not blank(value) for value in (second, third, dob, ni)):
                    name_failure(PERSONAL_REASON, [FIRST])
                elif blank(number):
                    name_failure("Surname is populated, but First Forename and Company Number fields are blank.", [FIRST, "Company Number"], COMPANY)
            name = surname.strip(" ")
            if len(name) == 1 and unicodedata.category(name).startswith("L"):
                name_failure("Surname contains only one letter. Please check this is correct.", [SURNAME])
            has_digit = lambda value: any(unicodedata.category(char) == "Nd" for char in value)
            numeric_fields = [field for field, value in (
                (FIRST, first), ("Customer Second Forename", second), ("Customer Third Forename", third),
                (SURNAME, surname if blank(number) else ""),
            ) if has_digit(value)]
            if numeric_fields:
                name_failure(NUMERIC, numeric_fields)
            if reasons:
                flag(1, record_index, scvid, "", [[scvid], [status], reasons, actions], fields)
        if enabled[2]:
            title_blank = blank(title)
            invalid = blank(number) if title_blank else title_key(title) not in TITLES
            if invalid:
                flag(2, record_index, scvid, "", [[scvid], [status], ["[Blank]" if title_blank else title], [TITLE_ACTION]])
        if enabled[4]:
            country, postcode = trim(get("Country")), trim(get("Post Code"))

            def flag_address(reason, field="Post Code"):
                flag(4, record_index, scvid, reason, [[scvid], [status], [postcode or "[Blank]"], [reason]], [field])

            for field in ("Address Line 1", "Address Line 2"):
                if not trim(get(field)):
                    flag_address(field + " is missing", field)
            upper = postcode.upper()
            if upper.startswith("BF1"):
                if not re.fullmatch("[A-Za-z0-9 ]+", postcode) or not BFPO_POSTCODE.fullmatch(upper):
                    flag_address("UK postcode has an invalid format")
                elif upper.replace(" ", "") not in BFPO_KEYS:
                    flag_address("BFPO postcode is not in the reference list; manual verification required.")
            elif not country or UK.fullmatch(country):
                if not postcode:
                    flag_address("UK postcode is missing")
                elif not re.fullmatch("[A-Za-z0-9 ]+", postcode) or not POSTCODE.fullmatch(upper):
                    flag_address("UK postcode has an invalid format")
                else:
                    key = upper.replace(" ", "")
                    postcode_rows.setdefault(key, []).append((record_index, scvid, status, postcode))
        if enabled[5] or enabled[6]:
            full_name = " ".join(trim(value) for value in (first, second, third, surname) if trim(value)).upper() if trim(first) and trim(surname) and blank(number) else ""
            missing_lines = []
            for i, (heading, value) in enumerate(zip(headers, record)):
                address = bool(re.fullmatch("Address Line [1-6]", heading))
                if not enabled[6] and not address:
                    continue
                matches = keywords(value, address or heading in NAME_FIELDS)
                if enabled[6]:
                    for match in matches:
                        reason = "NFFSTP keyword found: " + match
                        flag(6, record_index, scvid, [i, value, reason], [[scvid], [status], [heading], [value], [reason]])
                if not address or not enabled[5]:
                    continue

                def report_address(reason):
                    flag(5, record_index, scvid, [i, value, reason], [[scvid], [status], [heading], [value], [reason]])

                if int(heading[-1]) >= 3:
                    if not trim(value):
                        missing_lines.append(heading)
                    elif missing_lines:
                        report_address("Address line gap. Missing: " + ", ".join(missing_lines))
                for match in matches + word_matches(COMMENTS, value):
                    report_address("Address placeholder or comment: " + match)
                if full_name and trim(value).upper() == full_name and not re.match(r"^(?:C/O|CARE OF)\s", trim(value), re.I):
                    report_address("Address line contains the depositor’s name")
        if enabled[3]:
            for i, value in enumerate(record):
                invalid = list(dict.fromkeys(invalid_label(char) for char in value if ord(char) < 32 or ord(char) > 127))
                if invalid:
                    row = flag(3, record_index, scvid, i,
                               [[scvid], [status], [headers[i]], invalid, ["Please check if this character is correct"]])
                    values = row.setdefault("submittedValues", {}).setdefault(headers[i], [])
                    if value not in values:
                        values.append(value)
        if enabled[LENGTH_CHECK]:
            for field, limit in FIELD_MAX_LENGTHS.items():
                value = get(field)
                length = len(value)
                if length > limit:
                    reason = f"{field} exceeds the maximum length of {limit} characters ({length} submitted)."
                    flag(LENGTH_CHECK, record_index, scvid, [record_index, field, "overlength"],
                         [[scvid], [status], [field], [value], [reason]])
                if "  " in value:
                    reason = f"{field} contains consecutive spaces; please review."
                    flag(LENGTH_CHECK, record_index, scvid, [record_index, field, "spacing"],
                         [[scvid], [status], [field], [value], [reason]], grading_eligible=False)
        if submitted_rows is not None:
            submitted_record = submitted_rows[record_index + 1]
            for field_index, (field, value) in enumerate(zip(headers, submitted_record)):
                reason = speech_marks_reason(value)
                if reason:
                    flag(SPEECH_MARKS_CHECK, record_index, scvid, [record_index, field_index],
                         [[scvid], [status], [field], [value], [reason]])
        if enabled[DEPOSIT_CHECK]:
            field = "Transferable Eligible Deposit"
            value = get(field)
            amount = trim(value)
            if amount not in {"", "0", "0.00"}:
                reason = field + " must be blank, 0 or 0.00."
                flag(DEPOSIT_CHECK, record_index, scvid, value,
                     [[scvid], [status], [field], [value], [reason]])
    for scvid, row_indices in aggregate_rows.items():
        for row_index, submitted, expected, difference, reason, grade in aggregate_findings(records, index, row_indices):
            status = records[row_index][index["Account Status Code"]]
            flag(AGGREGATE_CHECK, row_index, scvid, [submitted, expected, difference, reason],
                 [[scvid], [status], [submitted], [expected], [difference], [reason]], grading_eligible=grade)
    release = None
    if postcode_rows:
        if lookup is None:
            raise ValidationError("The postcode reference lookup is required for FFSTP_12.")
        response = lookup(list(postcode_rows))
        release = response["release"]
        for key in response["missing"]:
            for row_index, scvid, status, postcode in postcode_rows[key]:
                reason = "UK postcode was not found in the postcode reference dataset"
                flag(4, row_index, scvid, reason, [[scvid], [status], [postcode], [reason]], ["Post Code"])
    result = {
        "records": len(records), "ids": len(ids), "affected": len(affected),
        "checksRun": [check[0] for check, active in zip(CHECKS, enabled) if active],
        "affectedRecords": [len(rows) for rows in affected_records],
        "gradingAffected": len(grading_affected),
        "gradingAffectedRecords": [len(rows) for rows in grading_affected_records],
        "results": [list(bucket.values()) for bucket in buckets],
    }
    if release:
        result["postcodeRelease"] = release
    return result


def make_test_file(records):
    def field_value(value):
        value = str(value)
        if any(char in value for char in ('"', '|', '\r', '\n')):
            raise ValidationError("Test data cannot contain double quotes, pipe delimiters or line breaks.")
        return value
    return "\r\n".join(["|".join(LAYOUT51)] + ["|".join(field_value(record.get(field, "")) for field in LAYOUT51) for record in records] + [MARKER])
