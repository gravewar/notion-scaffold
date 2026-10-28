"""Write every request body Scaffold sends into a TypeScript file typed with
Notion's official SDK, so `tsc` can check them against the real API schema.

    python tests/typecheck/dump_payloads.py > tests/typecheck/payloads.ts
    cd tests/typecheck && npm install && npx tsc
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fake_notion import FakeNotion  # noqa: E402

from scaffold.compose import Request, compose  # noqa: E402
from scaffold.deploy import Deployer  # noqa: E402
from scaffold.library import CONTEXTS, FEATURES  # noqa: E402

TYPES = {
    "create_page": "CreatePageParameters",
    "create_database": "CreateDatabaseParameters",
    "create_view": "ViewBody",
    "append_children": "AppendBlockChildrenParameters",
}

print("import type { CreatePageParameters, CreateDatabaseParameters, CreateViewParameters,",
      'AppendBlockChildrenParameters, QueryDataSourceParameters } from "@notionhq/client";\n')
# The SDK (5.28) types view filters and sorts as Record<string, never> placeholders.
# The API docs say they use the same format as data source queries, so check them against that.
print('type ViewBody = Omit<CreateViewParameters, "filter" | "sorts"> & {')
print('  filter?: QueryDataSourceParameters["filter"]; sorts?: QueryDataSourceParameters["sorts"] };\n')
n = 0
for ctx in CONTEXTS:
    fake = FakeNotion()
    Deployer(fake).deploy(compose(Request(context=ctx, categories=["Alpha", "Beta"], features=list(FEATURES))))
    for kind, body in fake.calls:
        if kind not in TYPES:
            continue
        if kind == "append_children":
            body = {"block_id": "x", **body}
        print(f"export const p{n}: {TYPES[kind]} = {json.dumps(body, ensure_ascii=False)};")
        n += 1
