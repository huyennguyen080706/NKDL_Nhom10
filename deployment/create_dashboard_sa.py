"""Tạo Service Account CHỈ ĐỌC cho dashboard Streamlit Cloud và sinh nội dung secrets.toml.

Chạy bởi người có quyền Owner trên project (dùng Application Default Credentials của người đó):

    .venv\\Scripts\\python deployment\\create_dashboard_sa.py

Script sẽ:
1. bật IAM API + Cloud Resource Manager API (nếu chưa bật);
2. tạo Service Account `streamlit-dashboard-reader` (bỏ qua nếu đã có);
3. gán đúng 2 role ở mức project: roles/bigquery.dataViewer (đọc bảng) và roles/bigquery.jobUser (chạy truy vấn);
4. tạo 1 key JSON và ghi ra NGOÀI repo:
     ../_secrets/streamlit-dashboard-reader-key.json
     ../_secrets/streamlit_secrets.toml   <- dán nguyên nội dung vào Streamlit Cloud (App settings -> Secrets)

Không ghi gì vào repo. Thu hồi quyền: xóa key/Service Account trong IAM & Admin của Google Cloud Console.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT = "vnstock-medallion-nhom10"
LOCATION = "asia-southeast1"
SA_ID = "streamlit-dashboard-reader"
EMAIL = f"{SA_ID}@{PROJECT}.iam.gserviceaccount.com"
ROLES = ["roles/bigquery.dataViewer", "roles/bigquery.jobUser"]
OUT_DIR = Path(__file__).resolve().parents[2] / "_secrets"


def main() -> int:
    cred, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    s = AuthorizedSession(cred)

    # 1. bật API
    r = s.post(f"https://serviceusage.googleapis.com/v1/projects/{PROJECT}/services:batchEnable",
               json={"serviceIds": ["iam.googleapis.com", "cloudresourcemanager.googleapis.com"]})
    r.raise_for_status()
    print("[1/4] Đã bật IAM API + Cloud Resource Manager API")

    # 2. tạo Service Account
    r = s.post(f"https://iam.googleapis.com/v1/projects/{PROJECT}/serviceAccounts", json={
        "accountId": SA_ID,
        "serviceAccount": {"displayName": "Streamlit dashboard (read-only BigQuery)"},
    })
    if r.status_code == 409:
        print(f"[2/4] Service Account đã tồn tại: {EMAIL}")
    else:
        r.raise_for_status()
        print(f"[2/4] Đã tạo Service Account: {EMAIL}")
        time.sleep(10)  # chờ SA lan truyền trước khi gán quyền

    # 3. gán role (đọc - sửa - ghi policy theo etag, thử lại nếu xung đột)
    crm = f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}"
    member = f"serviceAccount:{EMAIL}"
    for attempt in range(6):
        policy = s.post(crm + ":getIamPolicy", json={"options": {"requestedPolicyVersion": 3}}).json()
        bindings = policy.setdefault("bindings", [])
        for role in ROLES:
            b = next((b for b in bindings if b["role"] == role and "condition" not in b), None)
            if b is None:
                bindings.append({"role": role, "members": [member]})
            elif member not in b["members"]:
                b["members"].append(member)
        r = s.post(crm + ":setIamPolicy", json={"policy": policy})
        if r.ok:
            break
        print(f"      setIamPolicy thử lại ({r.status_code}): {r.text[:150]}")
        time.sleep(5)
    else:
        print("Không gán được quyền.", file=sys.stderr)
        return 1
    print(f"[3/4] Đã gán {', '.join(ROLES)}")

    # 4. tạo key + secrets.toml
    r = s.post(f"https://iam.googleapis.com/v1/projects/{PROJECT}/serviceAccounts/{EMAIL}/keys", json={})
    r.raise_for_status()
    key = json.loads(base64.b64decode(r.json()["privateKeyData"]))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key_path = OUT_DIR / f"{SA_ID}-key.json"
    key_path.write_text(json.dumps(key, indent=2), encoding="utf-8")

    lines = [
        'WAREHOUSE_BACKEND = "bigquery"',
        f'GCP_PROJECT_ID = "{PROJECT}"',
        f'BQ_LOCATION = "{LOCATION}"',
        "",
        "[gcp_service_account]",
    ]
    lines += [f"{k} = {json.dumps(v)}" for k, v in key.items()]  # json.dumps -> chuỗi TOML hợp lệ (giữ \n)
    toml_path = OUT_DIR / "streamlit_secrets.toml"
    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[4/4] Đã tạo key (id {key['private_key_id'][:8]}...)")
    print(f"      Key JSON : {key_path}")
    print(f"      Secrets  : {toml_path}")
    print("Xong. KHÔNG commit hai file trên; chỉ dán nội dung streamlit_secrets.toml vào Streamlit Cloud.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
