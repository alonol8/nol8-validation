# Go

This folder contains the runnable Use Case 2 benchmark implementation.

Implemented modes:
- `nocontrol`
- `re2_guard`
- `listguard`
- `nol8sim_infer`
- `nol8_api_infer` for engineering-only real API overlay work

The default customer-facing benchmark path remains the deterministic local modes.

Use `nol8_api_infer` only when:
- a real Nol8 endpoint is available
- engineering is validating measured API behavior
- you want report data that distinguishes real versus simulated modes
