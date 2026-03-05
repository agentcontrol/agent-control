# CHANGELOG

<!-- version list -->

## v6.4.0 (2026-03-05)

### Bug Fixes

- **ci**: Disable npm provenance for private TS SDK release
  ([#56](https://github.com/agentcontrol/agent-control/pull/56),
  [`ccb809f`](https://github.com/agentcontrol/agent-control/commit/ccb809f5f0f43ae10f7cc2c76b770352c49a4377))

- **docs**: Test all examples ([#16](https://github.com/agentcontrol/agent-control/pull/16),
  [`39e95c2`](https://github.com/agentcontrol/agent-control/commit/39e95c20dff4275fae9a44f305b0d1b354b3f24e))

- **sdk-ts**: Add conventional commits preset dependency
  ([#55](https://github.com/agentcontrol/agent-control/pull/55),
  [`540fe9d`](https://github.com/agentcontrol/agent-control/commit/540fe9df8fc69f223218ef2defbcc662ab3a902a))

- **sdk-ts**: Export npm token for semantic-release npm auth
  ([#54](https://github.com/agentcontrol/agent-control/pull/54),
  [`1b6b993`](https://github.com/agentcontrol/agent-control/commit/1b6b993eaed8c63ea4e61b21bc4fb27accaa2a49))

### Chores

- **docs**: Add npm badge ([#50](https://github.com/agentcontrol/agent-control/pull/50),
  [`b02b012`](https://github.com/agentcontrol/agent-control/commit/b02b01219f9079da420d75a1aee32262b150c76c))

- **release**: Ts sdk v1.0.0 [skip ci]
  ([`dfcc688`](https://github.com/agentcontrol/agent-control/commit/dfcc6888fd95c1743eb6f21a818945d19fba256f))

- **release**: Ts sdk v1.0.1 [skip ci]
  ([`f2a8497`](https://github.com/agentcontrol/agent-control/commit/f2a8497d42af12dcae7438e3b5a35914be600bec))

- **sdk-ts**: Make semantic-release workflow manual-only
  ([#53](https://github.com/agentcontrol/agent-control/pull/53),
  [`fe33556`](https://github.com/agentcontrol/agent-control/commit/fe33556c1b964cfc8204d0b6a5470a47a7bb8119))

### Features

- **infra**: Publish UI image and add compose UI service
  ([#57](https://github.com/agentcontrol/agent-control/pull/57),
  [`207c1af`](https://github.com/agentcontrol/agent-control/commit/207c1af3dec13b931abd1d9d2fcaa66ecbb2dc72))


## v6.3.0 (2026-03-04)

### Bug Fixes

- **ci**: Correct galileo contrib path in release build script
  ([#51](https://github.com/agentcontrol/agent-control/pull/51),
  [`2de6013`](https://github.com/agentcontrol/agent-control/commit/2de601338314b881f59847a5244b4226c74239f6))

### Features

- **sdk-ts**: Automate semantic-release for npm publishing
  ([#52](https://github.com/agentcontrol/agent-control/pull/52),
  [`2b43958`](https://github.com/agentcontrol/agent-control/commit/2b43958b6b2e850a044869f6f417194e1cb79d43))


## v6.2.0 (2026-03-04)

### Bug Fixes

- **docs**: Update Contributing Guide ([#8](https://github.com/agentcontrol/agent-control/pull/8),
  [`10b34c8`](https://github.com/agentcontrol/agent-control/commit/10b34c8bd4a3502b7844bc6daded4a08fde50442))

### Features

- **server**: Optional Policy and many to many relationships
  ([#41](https://github.com/agentcontrol/agent-control/pull/41),
  [`1a62746`](https://github.com/agentcontrol/agent-control/commit/1a627465a9266c6176f391e8f84f10304ba6a472))


## v6.1.0 (2026-03-03)

### Bug Fixes

- **docs**: Add setup script ([#49](https://github.com/agentcontrol/agent-control/pull/49),
  [`7a212c3`](https://github.com/agentcontrol/agent-control/commit/7a212c3d182ba3e07e56b0131957315b788f553a))

- **sdk**: 54253 add steer action and example
  ([#38](https://github.com/agentcontrol/agent-control/pull/38),
  [`bf2380a`](https://github.com/agentcontrol/agent-control/commit/bf2380aea5c879c77feb8f84a7fa14be5aa658b8))

### Features

- **sdk**: Refresh controls in a background loop
  ([#43](https://github.com/agentcontrol/agent-control/pull/43),
  [`03f826d`](https://github.com/agentcontrol/agent-control/commit/03f826d3e02f844d81c1a70ae4ea621a1788f9c7))


## v6.0.0 (2026-02-27)

### Bug Fixes

- **docs**: Update readme ([#37](https://github.com/agentcontrol/agent-control/pull/37),
  [`7531d83`](https://github.com/agentcontrol/agent-control/commit/7531d8309d4755d9ceddf4a2d840c147b36a6e14))

- **sdk**: A bug in docker file ([#46](https://github.com/agentcontrol/agent-control/pull/46),
  [`12d1794`](https://github.com/agentcontrol/agent-control/commit/12d1794e3e7218eef10e371e12b001774bd81a68))

- **server**: Feature/56688 fix docker and create bash
  ([#45](https://github.com/agentcontrol/agent-control/pull/45),
  [`7277e27`](https://github.com/agentcontrol/agent-control/commit/7277e2730c16e717ad5ba8248b946252b22e69cb))

- **server**: Feature/56688 fix image bug
  ([#48](https://github.com/agentcontrol/agent-control/pull/48),
  [`71e6b44`](https://github.com/agentcontrol/agent-control/commit/71e6b44f3cdee26c7a97a2cfc0ef6223e52bdb3a))

- **server**: Fix alembic migrations ([#47](https://github.com/agentcontrol/agent-control/pull/47),
  [`c19c17c`](https://github.com/agentcontrol/agent-control/commit/c19c17c6359b031bf5d69e81bfe72054bd09f40c))

- **ui**: Selector subpaths issue ([#34](https://github.com/agentcontrol/agent-control/pull/34),
  [`79cb776`](https://github.com/agentcontrol/agent-control/commit/79cb776032cedfacac5f9480151acf184a9921a3))

### Features

- **sdk**: Ship TypeScript SDK with deterministic method naming
  ([#32](https://github.com/agentcontrol/agent-control/pull/32),
  [`a76e9b0`](https://github.com/agentcontrol/agent-control/commit/a76e9b005a99b3d23eca9d77e498c3c6f0476559))

- **server**: Add initAgent conflict_mode overwrite mode with SDK defaults
  ([#40](https://github.com/agentcontrol/agent-control/pull/40),
  [`f3ed2b8`](https://github.com/agentcontrol/agent-control/commit/f3ed2b8a3207ff8fca324e0d01bdc33d768ce137))

- **server**: Hard-cut migrate to remove agent UUID
  ([#44](https://github.com/agentcontrol/agent-control/pull/44),
  [`ee322c9`](https://github.com/agentcontrol/agent-control/commit/ee322c93eb91f69a04895685176e4977bac21c15))

- **ui**: Allow to delete control ([#39](https://github.com/agentcontrol/agent-control/pull/39),
  [`7dc4ca3`](https://github.com/agentcontrol/agent-control/commit/7dc4ca3e3d6b38c7cacfdabca18b28a0ed310b58))

- **ui**: Steps dropdown rendered based on api return values
  ([#36](https://github.com/agentcontrol/agent-control/pull/36),
  [`a2aca43`](https://github.com/agentcontrol/agent-control/commit/a2aca43979d6089969408c3ee29f53a749b5cf1c))

- **ui**: Update agent control icon and favicon
  ([#42](https://github.com/agentcontrol/agent-control/pull/42),
  [`19af8fa`](https://github.com/agentcontrol/agent-control/commit/19af8faf26d5fb3dd895500f63108351cb77164b))


## v5.2.0 (2026-02-20)

### Bug Fixes

- **sdk**: Add step_name as parameter to control
  ([#25](https://github.com/agentcontrol/agent-control/pull/25),
  [`19ade9d`](https://github.com/agentcontrol/agent-control/commit/19ade9dcd69e264a62ccedf711722ef891d1b407))

- **sdk**: Emit observability events for SDK-evaluated controls and fix non_matches propagation
  ([#24](https://github.com/agentcontrol/agent-control/pull/24),
  [`6a9da69`](https://github.com/agentcontrol/agent-control/commit/6a9da69aeb89a0a0a207f05fcbb03f1260faa40e))

- **server**: Enforce public-safe API error responses
  ([#20](https://github.com/agentcontrol/agent-control/pull/20),
  [`e50d817`](https://github.com/agentcontrol/agent-control/commit/e50d817e2b81347c9143dcae8d461e7e3e581fd9))

- **ui**: Json validation ([#10](https://github.com/agentcontrol/agent-control/pull/10),
  [`a0cd5af`](https://github.com/agentcontrol/agent-control/commit/a0cd5af4a05a01fa7e5f8824001659ebc6bee7bc))

- **ui**: UI feedback fixes ([#27](https://github.com/agentcontrol/agent-control/pull/27),
  [`6004761`](https://github.com/agentcontrol/agent-control/commit/60047619ccbd1876100a38e02537d6987d8a02f7))

### Chores

- **ui**: Docs updates ([#21](https://github.com/agentcontrol/agent-control/pull/21),
  [`081a578`](https://github.com/agentcontrol/agent-control/commit/081a5784b360760983818dce2fbd55b91477bcd8))

- **ui**: Md cleanup ([#22](https://github.com/agentcontrol/agent-control/pull/22),
  [`744ea11`](https://github.com/agentcontrol/agent-control/commit/744ea1167497ccc43ee55194b800dce7f8d3a9ff))

- **ui**: UI feedback ([#17](https://github.com/agentcontrol/agent-control/pull/17),
  [`fbd6419`](https://github.com/agentcontrol/agent-control/commit/fbd6419468d5c1c6acee61c061f0ad6eee6e588e))

- **ui**: Update jds to latest ([#31](https://github.com/agentcontrol/agent-control/pull/31),
  [`bb3c5d0`](https://github.com/agentcontrol/agent-control/commit/bb3c5d0181cac81a697660b8d08bb84be88340c6))

### Features

- **evaluators**: Add required_column_values for multi-tenant SQL validation
  ([#30](https://github.com/agentcontrol/agent-control/pull/30),
  [`532386c`](https://github.com/agentcontrol/agent-control/commit/532386cb933e5d3f07c0939f41701500ef4f4007))

- **sdk**: Auto-populate init() steps from @control() decorators
  ([#23](https://github.com/agentcontrol/agent-control/pull/23),
  [`dc0f2a4`](https://github.com/agentcontrol/agent-control/commit/dc0f2a4061143a8e6de6a4a35677d229f14d03f9))


## v5.1.0 (2026-02-05)

### Documentation

- **examples**: Update examples and docs for evaluators reorganization
  ([#19](https://github.com/agentcontrol/agent-control/pull/19),
  [`9cb1851`](https://github.com/agentcontrol/agent-control/commit/9cb1851c442536aeb344bdbd889629167984e7da))

### Features

- **sdk**: Export ControlScope, ControlMatch, and EvaluatorResult models
  ([#18](https://github.com/agentcontrol/agent-control/pull/18),
  [`0d49cad`](https://github.com/agentcontrol/agent-control/commit/0d49cad9da5c9e76c32d652fadbc69cec698a611))


## v5.0.0 (2026-02-05)

### Bug Fixes

- **docs**: Add Example for Evaluator Extension
  ([#3](https://github.com/agentcontrol/agent-control/pull/3),
  [`c2a70b3`](https://github.com/agentcontrol/agent-control/commit/c2a70b335fb55481ad63b367ca87ba46de085343))

- **docs**: Update README ([#2](https://github.com/agentcontrol/agent-control/pull/2),
  [`379bb15`](https://github.com/agentcontrol/agent-control/commit/379bb158700b93aa549ef00eda57ccc2f88cb71f))

- **infra**: Install engine/evaluators in server image
  ([#14](https://github.com/agentcontrol/agent-control/pull/14),
  [`d5ae157`](https://github.com/agentcontrol/agent-control/commit/d5ae1571071afd34a00b376e650d9e1ce02f0b2d))

- **models**: Use StrEnum for error enums
  ([#12](https://github.com/agentcontrol/agent-control/pull/12),
  [`3f41c9f`](https://github.com/agentcontrol/agent-control/commit/3f41c9f974ba5afe873f30197aba7f2ff142f616))

- **server**: Reject initAgent UUID/name mismatch
  ([#13](https://github.com/agentcontrol/agent-control/pull/13),
  [`19d61ff`](https://github.com/agentcontrol/agent-control/commit/19d61ff1e1605925162eca31bacbe35eddeb5c17))

### Features

- **sdk**: Get Agent Controls from SDK Init
  ([#15](https://github.com/agentcontrol/agent-control/pull/15),
  [`a485f93`](https://github.com/agentcontrol/agent-control/commit/a485f93e15e49ddb975dee4bf4e24dfa3310d976))

### Refactoring

- **evaluators**: Split into builtin + extra packages for PyPI
  ([#5](https://github.com/agentcontrol/agent-control/pull/5),
  [`0e0a78a`](https://github.com/agentcontrol/agent-control/commit/0e0a78a9fa9c39a5709299c2e3d77c0609110280))

### Breaking Changes

- **evaluators**: Evaluator reorganization with new package structure


## v4.0.0 (2026-02-03)

### Bug Fixes

- Add tab level route ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Close all modals on success ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Limit height of tables ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- **ci**: Fix release ([#11](https://github.com/agentcontrol/agent-control/pull/11),
  [`9dd3dd7`](https://github.com/agentcontrol/agent-control/commit/9dd3dd795227f1d1db62e5ce2e8b336fe1c909f1))

- **models**: Update StatsRequest to match split API endpoints
  ([#6](https://github.com/agentcontrol/agent-control/pull/6),
  [`a0fa597`](https://github.com/agentcontrol/agent-control/commit/a0fa5977bdba2080612ac43320de3e786748e865))

- **sdk**: Enforce UUID agent IDs ([#9](https://github.com/agentcontrol/agent-control/pull/9),
  [`5ccdbd0`](https://github.com/agentcontrol/agent-control/commit/5ccdbd04c73b50e86362ca3e4204cb0e84fa1b5c))

- **tests**: Avoid init agent UUID conflicts
  ([#9](https://github.com/agentcontrol/agent-control/pull/9),
  [`5ccdbd0`](https://github.com/agentcontrol/agent-control/commit/5ccdbd04c73b50e86362ca3e4204cb0e84fa1b5c))

### Chores

- Control name error rendering ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Fix tests ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

- Folder structure cleanup and update tests
  ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

- Initial set of fixes for monitoring ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Observability minor fixes, code refactoring
  ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Remove scrollarea for sticky header to work.
  ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Return agent name and id with list of controls
  ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

- **tests**: Remove obsolete MemoryEventStore tests
  ([#6](https://github.com/agentcontrol/agent-control/pull/6),
  [`a0fa597`](https://github.com/agentcontrol/agent-control/commit/a0fa5977bdba2080612ac43320de3e786748e865))

- **ui**: UI fixes ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

### Features

- Basic setup for evaluator store flow ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

- Inital set of ui fixes ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Initial setup to support qp in modals + update tests
  ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Observability ui updated ([#7](https://github.com/agentcontrol/agent-control/pull/7),
  [`8e40b57`](https://github.com/agentcontrol/agent-control/commit/8e40b570f97fd9f91a25c57491eec1e0a35f3efd))

- Render controls in the control store, update ui and flow changes
  ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

- Search driven via backend, redirections and make it sync with query param
  ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

- **server**: Add extended time ranges (30d, 180d, 365d)
  ([#6](https://github.com/agentcontrol/agent-control/pull/6),
  [`a0fa597`](https://github.com/agentcontrol/agent-control/commit/a0fa5977bdba2080612ac43320de3e786748e865))

- **server**: Add time-series stats and split API endpoints
  ([#6](https://github.com/agentcontrol/agent-control/pull/6),
  [`a0fa597`](https://github.com/agentcontrol/agent-control/commit/a0fa5977bdba2080612ac43320de3e786748e865))

- **ui**: Control Store Flow Updated ([#4](https://github.com/agentcontrol/agent-control/pull/4),
  [`dda9f70`](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))

### Testing

- **sdk**: Add UUID validation coverage ([#9](https://github.com/agentcontrol/agent-control/pull/9),
  [`5ccdbd0`](https://github.com/agentcontrol/agent-control/commit/5ccdbd04c73b50e86362ca3e4204cb0e84fa1b5c))


## v3.0.0 (2026-01-30)

### Bug Fixes

- Tighten evaluation error handling and preserve control data
  ([`52a1ef8`](https://github.com/agentcontrol/agent-control/commit/52a1ef8127aca382e373ee6b6433a2d527e6e5e2))

- **examples**: Update crew ai example to use evaluator
  ([#93](https://github.com/agentcontrol/agent-control/pull/93),
  [`1c65084`](https://github.com/agentcontrol/agent-control/commit/1c6508434860ed5bb56c622a721197c5a8f7ad4e))

- **sdk**: Fix logging ([#77](https://github.com/agentcontrol/agent-control/pull/77),
  [`b1f078c`](https://github.com/agentcontrol/agent-control/commit/b1f078c52c29ac048a9bcbea09252786e842acbd))

- **sdk**: Plugin to evaluator.. agent_protect to agent_control
  ([#88](https://github.com/agentcontrol/agent-control/pull/88),
  [`fc9b088`](https://github.com/agentcontrol/agent-control/commit/fc9b088fcd091132a1e38deae372b73fc2834beb))

- **ui**: Fix UI and clients for simplified step schema
  ([#75](https://github.com/agentcontrol/agent-control/pull/75),
  [`be2aaf0`](https://github.com/agentcontrol/agent-control/commit/be2aaf0ae43a9051cb60ce3597f089307f731d0a))

### Documentation

- **examples**: Add crew ai example ([#84](https://github.com/agentcontrol/agent-control/pull/84),
  [`1077c3b`](https://github.com/agentcontrol/agent-control/commit/1077c3b9281ece7885383dccf58dbf0e4e70080e))

### Features

- **docs**: Add GitHub badges and CI coverage reporting
  ([#90](https://github.com/agentcontrol/agent-control/pull/90),
  [`be1fa14`](https://github.com/agentcontrol/agent-control/commit/be1fa140e4208993886f0afaef29b4a45fd27253))

- **ui**: Stats dashboard ([#80](https://github.com/agentcontrol/agent-control/pull/80),
  [`4cbb7fe`](https://github.com/agentcontrol/agent-control/commit/4cbb7fee43ed14145815c9fd807b150f19200654))

### Refactoring

- **evaluators**: Rename plugin to evaluator throughout
  ([#81](https://github.com/agentcontrol/agent-control/pull/81),
  [`0134682`](https://github.com/agentcontrol/agent-control/commit/0134682c1d0f167528d7267507dbcf3a1e7b3192))

### Testing

- **server**: Add behavioral coverage for controls, agents - follow up
  ([#95](https://github.com/agentcontrol/agent-control/pull/95),
  [`dfa9c3f`](https://github.com/agentcontrol/agent-control/commit/dfa9c3f2b110c96041893e392b3a11ab02cafcdb))

- **server**: Add behavioral coverage for controls, agents, observability
  ([#91](https://github.com/agentcontrol/agent-control/pull/91),
  [`d5c2301`](https://github.com/agentcontrol/agent-control/commit/d5c2301a8707ad9b4c84400f64695c53505d479a))


## v2.1.0 (2026-01-27)

### Features

- **server**: Add evaluator config store
  ([#78](https://github.com/agentcontrol/agent-control/pull/78),
  [`cc14aa6`](https://github.com/agentcontrol/agent-control/commit/cc14aa68391fd7fd4a187364a0a9a9fe712129fe))


## v2.0.1 (2026-01-26)

### Bug Fixes

- **docs**: Clean up Protect ([#76](https://github.com/agentcontrol/agent-control/pull/76),
  [`99c16fd`](https://github.com/agentcontrol/agent-control/commit/99c16fd8ed6620363f919818ebe4083f1489ba1c))


## v2.0.0 (2026-01-24)

### Features

- **server**: Add observability system for control execution tracking
  ([#44](https://github.com/agentcontrol/agent-control/pull/44),
  [`fd0bddc`](https://github.com/agentcontrol/agent-control/commit/fd0bddce3a9aa53472edb13e1c8fee6305571e98))

### Refactoring

- **models**: Simplify step model and schema
  ([#70](https://github.com/agentcontrol/agent-control/pull/70),
  [`4c1d637`](https://github.com/agentcontrol/agent-control/commit/4c1d6378a4a05edc44f02fa78c1698b9203da81b))


## v1.1.4 (2026-01-23)

### Chores

- **infra**: Rename project from agent-control to agent-control-sdk
  ([#74](https://github.com/agentcontrol/agent-control/pull/74),
  [`7a16463`](https://github.com/agentcontrol/agent-control/commit/7a1646341d4b4fc4edc1ab67a202c14ffb485934))


## v1.1.3 (2026-01-23)

### Chores

- **infra**: Rename sdk to agent-control
  ([#73](https://github.com/agentcontrol/agent-control/pull/73),
  [`2a4c88a`](https://github.com/agentcontrol/agent-control/commit/2a4c88a1d0c69bb71c7b61df7e636b7a8ef0a002))


## v1.1.2 (2026-01-23)

### Chores

- **infra**: Use pypi token for publish ([#72](https://github.com/agentcontrol/agent-control/pull/72),
  [`3f3ef15`](https://github.com/agentcontrol/agent-control/commit/3f3ef154fd22012d38932e3a461b08ce417c4e84))


## v1.1.1 (2026-01-23)

### Chores

- **infra**: Publish models and sdk on release
  ([#71](https://github.com/agentcontrol/agent-control/pull/71),
  [`7fcf53a`](https://github.com/agentcontrol/agent-control/commit/7fcf53a4392752e21f9eba77498bcc9ec2593bce))


## v1.1.0 (2026-01-23)

### Bug Fixes

- **ci**: Add ui scope to PR title validation
  ([#59](https://github.com/agentcontrol/agent-control/pull/59),
  [`e0fdb52`](https://github.com/agentcontrol/agent-control/commit/e0fdb528c201e15bab06668683ee02ef1dde70e8))

- **docs**: Fix Examples for LangGraph ([#64](https://github.com/agentcontrol/agent-control/pull/64),
  [`23b30ae`](https://github.com/agentcontrol/agent-control/commit/23b30ae1ddc5b878d8375b4f39a6617e7a0ae604))

- **docs**: Improve documentation for open source release
  ([#47](https://github.com/agentcontrol/agent-control/pull/47),
  [`9018fb3`](https://github.com/agentcontrol/agent-control/commit/9018fb3c79e385732957bafcf75dcec4f83b958d))

- **docs**: Remove old/unused examples ([#66](https://github.com/agentcontrol/agent-control/pull/66),
  [`f417781`](https://github.com/agentcontrol/agent-control/commit/f4177810579037a6c3f14cc4db59222166ec5209))

- **examples**: Control sets cleanup with signed
  ([#65](https://github.com/agentcontrol/agent-control/pull/65),
  [`af7b5fb`](https://github.com/agentcontrol/agent-control/commit/af7b5fb44fe800a98c617ee70ae258576e146115))

### Chores

- **ui**: Update and add readme & agents md
  ([#60](https://github.com/agentcontrol/agent-control/pull/60),
  [`53d46ec`](https://github.com/agentcontrol/agent-control/commit/53d46ec509d47a0e8da8abc4a060396bf4addffc))

### Features

- **server**: Add prometheus metrics for endpoints
  ([#68](https://github.com/agentcontrol/agent-control/pull/68),
  [`775612c`](https://github.com/agentcontrol/agent-control/commit/775612c2ebe4895760c326bb8e23ee29a5101247))

- **ui**: Add sql, luna2, json control forms and restructure the code
  ([#54](https://github.com/agentcontrol/agent-control/pull/54),
  [`c4c1d4a`](https://github.com/agentcontrol/agent-control/commit/c4c1d4ab53bce9bb9ee77657d4b9dd3152e587cd))

- **ui**: Tests added and some minor ui changes, added error boundaries
  ([#61](https://github.com/agentcontrol/agent-control/pull/61),
  [`009852b`](https://github.com/agentcontrol/agent-control/commit/009852bb678d570d21de82fb1af89eececd2fdc8))


## v1.0.1 (2026-01-17)

### Bug Fixes

- **infra**: Add plugins directory to Dockerfile
  ([#58](https://github.com/agentcontrol/agent-control/pull/58),
  [`171d459`](https://github.com/agentcontrol/agent-control/commit/171d459377aa294087f0af1561345a5e010120cb))


## v1.0.0 (2026-01-17)

- Initial Release
