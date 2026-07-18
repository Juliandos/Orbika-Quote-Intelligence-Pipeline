#!/usr/bin/env bash
# Reprocesa una cotización. Uso: ./reprocesar.sh <quote_key> <matching|agentic>
set -u
QK="${1:?falta quote_key}"; MODE="${2:-agentic}"
if [ "$MODE" = "matching" ]; then
  EP="supplier-matching"; BODY="{\"limit_per_part\":5,\"quote_keys\":[\"$QK\"]}"
else
  EP="agentic-review"; BODY="{\"limit_per_part\":5,\"disable_traces\":false,\"quote_keys\":[\"$QK\"]}"
fi
TID=$(curl -s -X POST "http://127.0.0.1/api/tasks/${EP}/run" -H 'Content-Type: application/json' -d "$BODY" \
      | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
echo "task $TID ($MODE sobre $QK)"
for i in $(seq 1 40); do
  sleep 8
  ST=$(curl -s http://127.0.0.1/api/tasks | python3 -c "import sys,json;ts=json.load(sys.stdin);ts=ts if isinstance(ts,list) else ts.get('tasks',[]);t=[x for x in ts if x.get('id')=='$TID'];print(t[0]['status'],t[0].get('exit_code')) if t else print('?')" 2>/dev/null)
  case "$ST" in
    completed*|finished*) echo "✅ $ST"; break;;
    failed*) echo "❌ $ST — ver /workspace/local/console_api/$TID.log en orbika-api"; break;;
    *) [ $((i%3)) -eq 0 ] && echo "  ...$((i*8))s ($ST)";;
  esac
done
