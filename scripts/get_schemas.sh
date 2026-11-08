#!/bin/bash
set -e
mkdir -p schema
curl -sSf -o schema/WasteContainer.schema.json https://raw.githubusercontent.com/smart-data-models/dataModel.WasteManagement/master/WasteContainer/schema.json
curl -sSf -o schema/common-schema.json https://raw.githubusercontent.com/smart-data-models/data-models/master/common-schema.json
echo "schemas in ./schema"
