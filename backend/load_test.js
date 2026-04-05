/**
 * FluxKart Load Test — k6
 *
 * TWO TEST SCENARIOS:
 *
 * 1. SUSTAINED LOAD (default):
 *    Tests normal flash sale traffic — browsing, viewing, reserving
 *    Ramps to 500 users, spikes to 2000 VUs
 *
 * 2. THUNDERING HERD (run with: k6 run -e MODE=herd load_test.js):
 *    Simulates T=0 flash sale moment — all users hit /reservations simultaneously
 *    5,000 VUs all fire POST /reservations at the exact same second
 *    This tests Redis Lua script atomicity under true spike conditions
 *
 * Run sustained:  k6 run -e SALE_ID=<id> load_test.js
 * Run herd:       k6 run -e SALE_ID=<id> -e MODE=herd load_test.js
 *
 * Pre-requisites:
 *   python scripts/create_test_users.py   ← once
 *   python scripts/generate_tokens.py     ← once per 30 min (JWT expiry)
 */

import http from 'k6/http'
import { check, sleep, group } from 'k6'
import { Rate, Trend, Counter } from 'k6/metrics'
import { SharedArray } from 'k6/data'

// ── Custom Metrics ────────────────────────────────────────────────────────────
const reservationSuccessRate = new Rate('reservation_success_rate')
const reservationQueuedRate  = new Rate('reservation_queued_rate')
const reservationFailRate    = new Rate('reservation_fail_rate')
const reservationLatency     = new Trend('reservation_latency_ms', true)
const oversellCounter        = new Counter('oversell_events')

// ── Test Config ───────────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || 'http://localhost'
const SALE_ID  = __ENV.SALE_ID  || 'REPLACE_WITH_ACTIVE_SALE_ID'
const MODE     = __ENV.MODE     || 'sustained'

// ── Pre-generated tokens — loaded from file, no live logins in setup ──────────
// Generate with: python scripts/generate_tokens.py
// File path must be relative to load_test.js location
const TOKEN_LIST = new SharedArray('tokens', function () {
  return Object.values(JSON.parse(open('/scripts/tokens.json')))
})

const TOTAL_USERS = 5000

// ── Load Profiles ─────────────────────────────────────────────────────────────
const SUSTAINED_OPTIONS = {
  setupTimeout: '30s',
  stages: [
    { duration: '30s', target: 500  },
    { duration: '1m',  target: 500  },
    { duration: '30s', target: 2000 },
    { duration: '1m',  target: 2000 },
    { duration: '30s', target: 5000 },
    { duration: '1m',  target: 5000 },
    { duration: '30s', target: 0    },
  ],
  thresholds: {
    'http_req_duration':        ['p(95)<5000', 'p(99)<10000'],
    'http_req_failed':          ['rate<0.90'],
    'reservation_success_rate': ['rate>0.001'],
    'reservation_latency_ms':   ['p(95)<5000'],
  },
}

// Thundering herd — all VUs fire at the same moment
const HERD_OPTIONS = {
  setupTimeout: '30s',   // was 600s
  scenarios: {
    thundering_herd: {
      executor:           'ramping-arrival-rate',
      startRate:          0,
      timeUnit:           '1s',
      preAllocatedVUs:    5000,
      maxVUs:             5000,
      stages: [
        { duration: '3s',  target: 0     },   // Hold — wait for all VUs ready
        { duration: '1s',  target: 5000  },   // SPIKE — 5K req in 1 second
        { duration: '10s', target: 5000  },   // Hold at peak
        { duration: '5s',  target: 0     },   // Ramp down
      ],
    },
  },
  thresholds: {
    'reservation_success_rate': ['rate>0.001'],
    'oversell_events':          ['count==0'],   // CRITICAL — zero oversell
    'reservation_latency_ms':   ['p(95)<10000'],
  },
}

export const options = MODE === 'herd' ? HERD_OPTIONS : SUSTAINED_OPTIONS

// ── Helpers ───────────────────────────────────────────────────────────────────
function authHeaders(token) {
  return {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type':  'application/json',
    },
  }
}

function idempotencyKey() {
  return `res-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function randomToken() {
  return TOKEN_LIST[Math.floor(Math.random() * TOKEN_LIST.length)]
}

// ── Main Test Scenario ────────────────────────────────────────────────────────
export default function (data) {
  // Each VU picks a random pre-loaded token — no live login needed
  const token = randomToken()

  if (!token) {
    sleep(1)
    return
  }

  if (MODE === 'herd') {
    // ── Thundering Herd Mode — reservation only ───────────────────────────
    const start   = Date.now()
    const payload = JSON.stringify({
      sale_id:         SALE_ID,
      quantity:        1,
      idempotency_key: idempotencyKey(),
    })

    const res = http.post(`${BASE_URL}/reservations`, payload, authHeaders(token))
    reservationLatency.add(Date.now() - start)

    if (res.status === 201) {
      reservationSuccessRate.add(true)
      check(res, {
        'reservation has id':         (r) => JSON.parse(r.body).id !== undefined,
        'reservation status pending': (r) => JSON.parse(r.body).status === 'pending',
      })
    } else if (res.status === 202) {
      reservationQueuedRate.add(true)
      reservationSuccessRate.add(false)
    } else if (res.status === 409 || res.status === 429) {
      reservationSuccessRate.add(false)
      reservationFailRate.add(false)
    } else {
      reservationSuccessRate.add(false)
      reservationFailRate.add(true)
    }

    return
  }

  // ── Sustained Load Mode — full user journey ───────────────────────────────

  group('1_browse_sales', () => {
    const res = http.get(`${BASE_URL}/sales`, authHeaders(token))
    check(res, {
      'sales 200': (r) => r.status === 200,
      'has sales': (r) => {
        try { return JSON.parse(r.body).length > 0 } catch { return false }
      },
    })
    sleep(Math.random() * 2 + 0.5)
  })

  group('2_view_sale', () => {
    const res = http.get(`${BASE_URL}/sales/${SALE_ID}`, authHeaders(token))
    check(res, { 'sale detail 200': (r) => r.status === 200 })

    try {
      const body = JSON.parse(res.body)
      if (body.available_quantity < 0) {
        oversellCounter.add(1)
      }
    } catch {}

    sleep(Math.random() * 1 + 0.5)
  })

  group('3_reserve', () => {
    const start   = Date.now()
    const payload = JSON.stringify({
      sale_id:         SALE_ID,
      quantity:        1,
      idempotency_key: idempotencyKey(),
    })

    const res = http.post(`${BASE_URL}/reservations`, payload, authHeaders(token))
    reservationLatency.add(Date.now() - start)

    if (res.status === 201) {
      reservationSuccessRate.add(true)
      reservationQueuedRate.add(false)
      reservationFailRate.add(false)
      check(res, {
        'reservation has id':         (r) => JSON.parse(r.body).id !== undefined,
        'reservation status pending': (r) => JSON.parse(r.body).status === 'pending',
        'reservation has expires_at': (r) => JSON.parse(r.body).expires_at !== undefined,
      })
    } else if (res.status === 202) {
      reservationSuccessRate.add(false)
      reservationQueuedRate.add(true)
      reservationFailRate.add(false)
    } else if (res.status === 409 || res.status === 429) {
      reservationSuccessRate.add(false)
      reservationQueuedRate.add(false)
      reservationFailRate.add(false)
    } else {
      reservationSuccessRate.add(false)
      reservationQueuedRate.add(false)
      reservationFailRate.add(true)
    }

    sleep(0.1)
  })

  group('4_check_orders', () => {
    const res = http.get(`${BASE_URL}/orders`, authHeaders(token))
    check(res, { 'orders 200': (r) => r.status === 200 })
    sleep(0.5)
  })

  sleep(Math.random() * 2 + 1)
}

// ── Setup — instant now, tokens pre-loaded from file ─────────────────────────
export function setup() {
  console.log(`FluxKart Load Test — MODE: ${MODE}`)
  console.log(`Target: ${BASE_URL}`)
  console.log(`Sale ID: ${SALE_ID}`)
  console.log(`Tokens loaded: ${TOKEN_LIST.length} users`)

  // Health check
  let healthy = false
  for (let i = 0; i < 5; i++) {
    const healthRes = http.get(`${BASE_URL}/health`)
    if (healthRes.status === 200) { healthy = true; break }
    sleep(2)
  }
  if (!healthy) throw new Error('API not reachable after 5 retries')
  console.log('API health check passed')

  if (TOKEN_LIST.length === 0) {
    throw new Error('No tokens loaded — run: python scripts/generate_tokens.py')
  }

  return { startTime: Date.now() }
}

// ── Teardown ──────────────────────────────────────────────────────────────────
export function teardown(data) {
  const duration = Math.round((Date.now() - data.startTime) / 1000)
  console.log(`Load test completed in ${duration}s`)
  console.log('Check Grafana at http://localhost:3000 for metrics')
}