#!/bin/bash
# IdM SRE Lab - End-to-End Smoke Test (Week 29-30)
# 覆盖 7 大模块：OAuth → SAML → WebAuthn → Devices → Observability → Chaos → Incident → Post-Mortem
set -e

BASE_URL=${BASE_URL:-http://127.0.0.1:5050}
PASS=0
FAIL=0
COOKIE_JAR=/tmp/idm-e2e-cookies.txt

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

step() {
    echo ""
    echo "=== $1 ==="
}

check() {
    local desc=$1
    local cmd=$2
    if eval "$cmd" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $desc"
        PASS=$((PASS+1))
    else
        echo -e "${RED}✗${NC} $desc"
        FAIL=$((FAIL+1))
    fi
}

# ============================================
# 0. Health + Seed
# ============================================
step "0. Health + Seed"
check "Health check" "curl -fsS $BASE_URL/health | grep -q 'ok'"
check "Reseed data" "curl -fsS -X POST $BASE_URL/admin/seed > /dev/null"

# ============================================
# 1. OAuth2/OIDC (Week 3-4)
# ============================================
step "1. OAuth2/OIDC (Week 3-4)"
check "Discovery endpoint" "curl -fsS $BASE_URL/.well-known/openid-configuration | grep -q 'authorization_endpoint'"
check "JWKS endpoint" "curl -fsS $BASE_URL/.well-known/jwks.json | grep -q 'keys'"

# Login flow
LOC=$(curl -s -X POST $BASE_URL/oauth/authorize \
    -d "username=engineer01&password=Engineer@2026&client_id=tripbiz-booking-app&redirect_uri=$BASE_URL/callback&scope=openid+profile+email" \
    -o /dev/null -w "%{redirect_url}")
CODE=$(echo "$LOC" | sed -n 's/.*code=\([^&]*\).*/\1/p')
[ -n "$CODE" ] && echo -e "${GREEN}✓${NC} Auth code issued" && PASS=$((PASS+1)) || { echo -e "${RED}✗${NC} Auth code failed"; FAIL=$((FAIL+1)); }

TOKEN_JSON=$(curl -s -X POST $BASE_URL/oauth/token \
    -d "grant_type=authorization_code&code=$CODE&redirect_uri=$BASE_URL/callback&client_id=tripbiz-booking-app&client_secret=tripbiz-booking-app-secret-2026")
ACCESS=$(echo "$TOKEN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
[ -n "$ACCESS" ] && echo -e "${GREEN}✓${NC} Token issued" && PASS=$((PASS+1)) || { echo -e "${RED}✗${NC} Token failed"; FAIL=$((FAIL+1)); }

check "UserInfo with Bearer" "curl -fsS -H 'Authorization: Bearer $ACCESS' $BASE_URL/oauth/userinfo | grep -q 'USER-001'"
check "Token introspect" "curl -fsS -X POST $BASE_URL/oauth/introspect -d 'token=$ACCESS&client_id=tripbiz-booking-app&client_secret=tripbiz-booking-app-secret-2026' | grep -q 'active'"

# ============================================
# 2. SAML 2.0 (Week 5-6)
# ============================================
step "2. SAML 2.0 (Week 5-6)"
check "SP metadata" "curl -fsS $BASE_URL/saml/metadata | grep -q 'SPSSODescriptor'"
check "IdP metadata" "curl -fsS $BASE_URL/saml/idp-metadata | grep -q 'IDPSSODescriptor'"

# SSO flow
LOC=$(curl -s -X POST $BASE_URL/saml/login?RelayState=/x -o /dev/null -w "%{redirect_url}")
SAMLREQ=$(echo "$LOC" | sed -n 's/.*SAMLRequest=\([^&]*\).*/\1/p')
SAMLRESP=$(curl -s -X POST $BASE_URL/saml/idp/sso \
    -d "SAMLRequest=$SAMLREQ&RelayState=/x&username=engineer01&password=Engineer@2026" \
    -o /dev/null -w "%{redirect_url}" | sed -n 's/.*SAMLResponse=\([^&]*\).*/\1/p')
curl -s -c $COOKIE_JAR -L "$BASE_URL/saml/acs?SAMLResponse=$SAMLRESP&RelayState=/x" -o /dev/null
check "SAML userinfo with cookie" "curl -fsS -b $COOKIE_JAR $BASE_URL/saml/userinfo | grep -q 'USER-001'"

# ============================================
# 3. WebAuthn (Week 7-8)
# ============================================
step "3. WebAuthn (Week 7-8)"
CHAL=$(curl -fsS -X POST $BASE_URL/webauthn/register/begin -d "username=engineer01" | python3 -c "import sys,json; print(json.load(sys.stdin)['challenge'])")
[ -n "$CHAL" ] && echo -e "${GREEN}✓${NC} WebAuthn challenge issued" && PASS=$((PASS+1))

CRED="cred_e2e_$(date +%s)"
check "WebAuthn register finish" "curl -fsS -X POST $BASE_URL/webauthn/register/finish -d 'username=engineer01&challenge=$CHAL&credential_id=$CRED&friendly_name=E2E+Test' | grep -q 'registered'"

# Authenticate
CHAL2=$(curl -fsS -X POST $BASE_URL/webauthn/authenticate/begin -d "username=engineer01" | python3 -c "import sys,json; print(json.load(sys.stdin)['challenge'])")
SIG=$(python3 -c "
import sys
sys.path.insert(0, '/Users/jiangwenrui/Downloads/mass/idm-sre-lab')
from app.webauthn.webauthn_core import sign_challenge_response
print(sign_challenge_response('$CHAL2', '$CRED', 1))
")
check "WebAuthn authenticate" "curl -fsS -X POST $BASE_URL/webauthn/authenticate/finish -d 'username=engineer01&challenge=$CHAL2&credential_id=$CRED&counter=1&signature=$SIG' | grep -q 'authenticated'"

# ============================================
# 4. Devices Provisioning (Week 9-10)
# ============================================
step "4. Devices Provisioning (Week 9-10)"
DEV=$(curl -fsS -X POST $BASE_URL/devices \
    -d "device_name=E2E+Test+Device&user_id=USER-001&device_type=LAPTOP&os=Linux&serial_number=E2E-$RANDOM" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['device']['device_id'])")
[ -n "$DEV" ] && echo -e "${GREEN}✓${NC} Device registered" && PASS=$((PASS+1))
check "Device activate" "curl -fsS -X POST $BASE_URL/devices/$DEV/activate | grep -q 'ACTIVE'"
check "Device portfolio stats" "curl -fsS $BASE_URL/devices/portfolio/stats | grep -q 'total_devices'"

# ============================================
# 5. Observability (Week 13-14)
# ============================================
step "5. Observability (Week 13-14)"
check "Prometheus /metrics" "curl -fsS $BASE_URL/metrics | grep -q 'idm_requests_total'"
check "4 Golden Signals" "curl -fsS $BASE_URL/observability/signals | grep -q 'total_requests'"
check "Dashboard HTML" "curl -fsS $BASE_URL/observability/dashboard | grep -q 'Golden Signals'"

# ============================================
# 6. Chaos Engineering (Week 19-20)
# ============================================
step "6. Chaos Engineering (Week 19-20)"
EXP_ID=$(curl -fsS -X POST $BASE_URL/chaos/experiments \
    -d "experiment_type=latency_injection&target_service=e2e-test&duration_seconds=2&hypothesis=service+should+remain+stable" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['experiment_id'])")
[ -n "$EXP_ID" ] && echo -e "${GREEN}✓${NC} Chaos experiment created" && PASS=$((PASS+1))
check "Chaos run + verdict" "curl -fsS -X POST $BASE_URL/chaos/experiments/$EXP_ID/run | grep -q 'verdict'"

# ============================================
# 7. Incident Response (Week 21-22)
# ============================================
step "7. Incident Response (Week 21-22)"
check "Runbooks list" "curl -fsS $BASE_URL/runbooks | grep -q 'high_error_rate'"
INC_ID=$(curl -fsS -X POST $BASE_URL/incidents \
    -d "incident_type=auth_fail&title=E2E+test+incident&severity=SEV-2" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['incident_id'])")
[ -n "$INC_ID" ] && echo -e "${GREEN}✓${NC} Incident created" && PASS=$((PASS+1))
check "Resolve incident" "curl -fsS -X PATCH $BASE_URL/incidents/$INC_ID -d 'status=RESOLVED&lessons_learned=E2E+verified' | grep -q 'RESOLVED'"

# ============================================
# 8. Post-Mortem (Week 27-28)
# ============================================
step "8. Post-Mortem (Week 27-28)"
check "PM template" "curl -fsS $BASE_URL/pm-template | grep -q '5 Whys'"
PM_ID=$(curl -fsS -X POST $BASE_URL/pm-documents \
    -d "title=E2E+PM&severity=SEV-2&incident_id=$INC_ID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['pm_id'])")
[ -n "$PM_ID" ] && echo -e "${GREEN}✓${NC} PM created" && PASS=$((PASS+1))
check "Publish PM" "curl -fsS -X PATCH $BASE_URL/pm-documents/$PM_ID -d 'status=PUBLISHED' | grep -q 'PUBLISHED'"

# ============================================
# 9. GenAI Alert (Week 23-24)
# ============================================
step "9. GenAI Alert (Week 23-24)"
check "Show prompt template" "curl -fsS $BASE_URL/ai-alerts/prompt | grep -q 'system_prompt'"
check "Interpret alert (if LLM key set)" "[ -z \"\$LLM_API_KEY\" ] || curl -fsS -X POST $BASE_URL/ai-alerts/interpret -d 'alert_name=HighErrorRate&severity=critical&duration_minutes=1&metrics={\"total_requests\":50}' | grep -q 'interpretation'"

# ============================================
# 10. Security Compliance (Week 25-26)
# ============================================
step "10. Security Compliance (Week 25-26)"
check "ISO 27001 mapping" "curl -fsS $BASE_URL/security/iso27001/mapping | grep -q 'A.5'"
check "PCI-DSS mapping" "curl -fsS $BASE_URL/security/pci-dss/mapping | grep -q 'Section 8'"
check "STRIDE threat model" "curl -fsS $BASE_URL/security/threat-model | grep -q 'STRIDE'"
check "Security summary" "curl -fsS $BASE_URL/security/summary | grep -q 'iso27001_2022'"

# ============================================
# Summary
# ============================================
echo ""
echo "============================================"
echo "  E2E Smoke Summary: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
echo "============================================"
exit $FAIL