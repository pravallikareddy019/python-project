"""Regenerate the sample datasets in data/ (deterministic).

sample_data.csv / .json  - 40 student records: normal rows, boundary values, blanks / NA markers,
                           an outlier, a mixed-type cell, a very sparse column and a constant column.
                           The CSV also contains deliberately malformed lines (row-by-row error log demo).
sample_orders.csv        - 30 order records with a second set of column shapes.
"""
import csv
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
rng = random.Random(42)

FIRST = ["Aarav", "Ananya", "Vihaan", "Diya", "Arjun", "Isha", "Kabir", "Meera", "Rohan", "Saanvi",
         "Aditya", "Nisha", "Karthik", "Priya", "Rahul", "Sneha", "Vivek", "Tara", "Manish", "Lakshmi",
         "Harsh", "Pooja", "Siddharth", "Divya", "Nikhil", "Riya", "Varun", "Kavya", "Dev", "Anjali",
         "Imran", "Zoya", "Gautam", "Neha", "Yash", "Sana", "Omkar", "Bhavna", "Tejas", "Mira"]
LAST = ["Sharma", "Reddy", "Patel", "Iyer", "Nair", "Gupta", "Khan", "Das", "Rao", "Menon"]
DEPTS = ["Computer Science", "Electronics", "Mechanical", "Civil", "Mathematics", "Physics"]


def students():
    rows = []
    for i in range(40):
        name = f"{FIRST[i]} {LAST[i % len(LAST)]}"
        age = rng.choice([18, 19, 19, 20, 20, 21, 21, 22, 23])
        gpa = round(rng.uniform(5.5, 9.8) / 2.5, 2)            # 0-4 scale
        rows.append({
            "student_id": f"S{1001 + i}",
            "full_name": name,
            "department": rng.choice(DEPTS),
            "age": str(age),
            "gpa": f"{min(gpa, 4.0):.2f}",
            "attendance_pct": str(rng.randint(62, 99)),
            "credits": str(rng.choice([12, 15, 15, 18, 18, 21])),
            "enrolled_on": f"2024-{rng.randint(8, 9):02d}-{rng.randint(1, 28):02d}"
                           if i % 4 else f"2025-0{rng.randint(1, 9)}-{rng.randint(10, 28)}",
            "scholarship": rng.choice(["yes", "no", "no"]),
            "email": f"{name.split()[0].lower()}.{name.split()[1].lower()}@campus.edu",
            "mentor_id": f"M{rng.randint(10, 40)}" if i % 5 == 0 else "",
            "campus": "Main",
        })
    # --- boundary values and edge conditions --------------------------------------------
    rows[0].update(gpa="4.00", attendance_pct="100")             # upper boundaries
    rows[1].update(gpa="0.00", attendance_pct="0")               # lower boundaries
    rows[2].update(age="17")                                     # youngest allowed
    rows[3].update(age="61")                                     # outlier
    rows[4].update(age="twenty")                                 # mixed-type cell
    rows[5].update(attendance_pct="250")                         # impossible value -> outlier
    rows[6].update(age="")                                       # blank
    for idx in (7, 11, 15, 19, 23):
        rows[idx].update(gpa="NA")                               # missing markers
    for idx in (8, 16):
        rows[idx].update(gpa="")
    for idx in (9, 13, 21, 22, 26, 30, 34, 38):
        rows[idx].update(email="")                               # email ~20% missing
    for idx in (10, 20):
        rows[idx].update(scholarship="")
    rows[12].update(attendance_pct="null")
    rows[39].update(enrolled_on="2025-09-01")
    return rows


def write_students(rows):
    fields = list(rows[0].keys())
    lines = []
    with (OUT / "sample_data.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for i, r in enumerate(rows):
            values = [r[f] for f in fields]
            if i == 25:                       # short row: trailing cells missing -> padded on import
                values = values[:9]
            w.writerow(values)
            if i == 12:                       # extra cells -> rejected with an error-log entry
                w.writerow(["S9999", "Broken Row", "Physics", "20", "3.1", "88", "15",
                            "2025-01-05", "yes", "broken@campus.edu", "", "Main", "UNEXPECTED", "EXTRA"])
            if i == 33:                       # blank line -> skipped
                fh.write("\n")
    # JSON: same 40 records as an array of objects (empty strings -> null)
    records = [{k: (v if v != "" else None) for k, v in r.items()} for r in rows]
    (OUT / "sample_data.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def orders():
    products = [("Laptop stand", 24.5), ("USB-C hub", 39.9), ("Mechanical keyboard", 89.0),
                ("Webcam", 54.25), ("Desk lamp", 31.0), ("Notebook pack", 12.75), ("Monitor arm", 67.4)]
    statuses = ["Delivered", "Delivered", "Shipped", "Pending", "Cancelled"]
    rows = []
    for i in range(30):
        product, price = rng.choice(products)
        status = rng.choice(statuses)
        rows.append({
            "order_id": f"O-{5001 + i}",
            "customer": f"{FIRST[(i * 3) % 40]} {LAST[(i * 7) % 10]}",
            "product": product,
            "quantity": str(rng.randint(1, 8)),
            "unit_price": f"{price:.2f}",
            "order_date": f"2026-{rng.randint(3, 10):02d}-{rng.randint(1, 28):02d}",
            "status": status,
            "shipped": "true" if status in ("Delivered", "Shipped") else "false",
            "discount_pct": str(rng.choice([5, 10, 15])) if i % 3 == 0 else "",
            "rating": str(rng.randint(1, 5)) if status == "Delivered" and i % 4 else "",
        })
    rows[0].update(quantity="0")                    # boundary
    rows[1].update(quantity="500")                  # outlier (bulk order)
    rows[2].update(unit_price="NA")
    rows[3].update(unit_price="-")
    rows[4].update(rating="5", shipped="true")
    return rows


def write_orders(rows):
    with (OUT / "sample_orders.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    write_students(students())
    write_orders(orders())
    print("Wrote sample_data.csv, sample_data.json, sample_orders.csv to", OUT)
