## [1.0.1](https://github.com/agentcontrol/agent-control/compare/ts-sdk-v1.0.0...ts-sdk-v1.0.1) (2026-03-04)

### Bug Fixes

* **ci:** disable npm provenance for private TS SDK release ([#56](https://github.com/agentcontrol/agent-control/issues/56)) ([ccb809f](https://github.com/agentcontrol/agent-control/commit/ccb809f5f0f43ae10f7cc2c76b770352c49a4377))

## 1.0.0 (2026-03-04)

### ⚠ BREAKING CHANGES

* **server:** Feature/56688 fix image bug (#48)
* **sdk:** a bug in docker file (#46)
* **server:** Feature/56688 fix docker and create bash (#45)
* **evaluators:** Evaluator reorganization with new package structure

Package Structure:
- agent-control-evaluators (v3.0.0): core + regex, list, json, sql
- agent-control-evaluator-galileo (v3.0.0): Luna2 evaluator

Key Changes:
- Entry points for evaluator discovery (agent_control.evaluators)
- Dot notation for external evaluators (galileo.luna2 not galileo/luna2)
- Dynamic __version__ via importlib.metadata
- Server uses evaluators as runtime dep (no longer vendored)
- Release workflow publishes both packages to PyPI

Bug Fixes:
- JSON evaluator: field_constraints/field_patterns in extra-fields allow-list
- SQL evaluator: LIMIT/OFFSET bypass fix

Migration:
- Import: agent_control_evaluator_galileo.luna2 (not agent_control_evaluators.galileo_luna2)
- DB: UPDATE controls SET evaluator.name replace('/', '.')
* **server:** add time-series stats and split API endpoints (#6)
* **evaluators:** rename plugin to evaluator throughout  (#81)
* **models:** simplify step model and schema (#70)

### Features

* Add plugin auto-discovery via Python entry points ([#49](https://github.com/agentcontrol/agent-control/issues/49)) ([1521182](https://github.com/agentcontrol/agent-control/commit/1521182c3adbad9cd160c465bdc8fc7ebb6e14ae))
* **docs:** add GitHub badges and CI coverage reporting ([#90](https://github.com/agentcontrol/agent-control/issues/90)) ([be1fa14](https://github.com/agentcontrol/agent-control/commit/be1fa140e4208993886f0afaef29b4a45fd27253))
* **evaluators:** add required_column_values for multi-tenant SQL validation ([#30](https://github.com/agentcontrol/agent-control/issues/30)) ([532386c](https://github.com/agentcontrol/agent-control/commit/532386cb933e5d3f07c0939f41701500ef4f4007))
* **sdk-ts:** automate semantic-release for npm publishing ([#52](https://github.com/agentcontrol/agent-control/issues/52)) ([2b43958](https://github.com/agentcontrol/agent-control/commit/2b43958b6b2e850a044869f6f417194e1cb79d43))
* **sdk:** Add PyPI packaging with semantic release ([#52](https://github.com/agentcontrol/agent-control/issues/52)) ([7c24f7f](https://github.com/agentcontrol/agent-control/commit/7c24f7f1ceee94b31098b3e3dd5ada1c16aa0f68))
* **sdk:** Auto-populate init() steps from [@control](https://github.com/control)() decorators ([#23](https://github.com/agentcontrol/agent-control/issues/23)) ([dc0f2a4](https://github.com/agentcontrol/agent-control/commit/dc0f2a4061143a8e6de6a4a35677d229f14d03f9))
* **sdk:** export ControlScope, ControlMatch, and EvaluatorResult models ([#18](https://github.com/agentcontrol/agent-control/issues/18)) ([0d49cad](https://github.com/agentcontrol/agent-control/commit/0d49cad9da5c9e76c32d652fadbc69cec698a611))
* **sdk:** Get Agent Controls from SDK Init ([#15](https://github.com/agentcontrol/agent-control/issues/15)) ([a485f93](https://github.com/agentcontrol/agent-control/commit/a485f93e15e49ddb975dee4bf4e24dfa3310d976))
* **sdk:** Refresh controls in a background loop ([#43](https://github.com/agentcontrol/agent-control/issues/43)) ([03f826d](https://github.com/agentcontrol/agent-control/commit/03f826d3e02f844d81c1a70ae4ea621a1788f9c7))
* **sdk:** ship TypeScript SDK with deterministic method naming ([#32](https://github.com/agentcontrol/agent-control/issues/32)) ([a76e9b0](https://github.com/agentcontrol/agent-control/commit/a76e9b005a99b3d23eca9d77e498c3c6f0476559))
* **server:** add evaluator config store ([#78](https://github.com/agentcontrol/agent-control/issues/78)) ([cc14aa6](https://github.com/agentcontrol/agent-control/commit/cc14aa68391fd7fd4a187364a0a9a9fe712129fe))
* **server:** add initAgent conflict_mode overwrite mode with SDK defaults ([#40](https://github.com/agentcontrol/agent-control/issues/40)) ([f3ed2b8](https://github.com/agentcontrol/agent-control/commit/f3ed2b8a3207ff8fca324e0d01bdc33d768ce137))
* **server:** Add observability system for control execution tracking ([#44](https://github.com/agentcontrol/agent-control/issues/44)) ([fd0bddc](https://github.com/agentcontrol/agent-control/commit/fd0bddce3a9aa53472edb13e1c8fee6305571e98))
* **server:** add prometheus metrics for endpoints ([#68](https://github.com/agentcontrol/agent-control/issues/68)) ([775612c](https://github.com/agentcontrol/agent-control/commit/775612c2ebe4895760c326bb8e23ee29a5101247))
* **server:** add time-series stats and split API endpoints ([#6](https://github.com/agentcontrol/agent-control/issues/6)) ([a0fa597](https://github.com/agentcontrol/agent-control/commit/a0fa5977bdba2080612ac43320de3e786748e865))
* **server:** hard-cut migrate to remove agent UUID ([#44](https://github.com/agentcontrol/agent-control/issues/44)) ([ee322c9](https://github.com/agentcontrol/agent-control/commit/ee322c93eb91f69a04895685176e4977bac21c15))
* **server:** Optional Policy and many to many relationships ([#41](https://github.com/agentcontrol/agent-control/issues/41)) ([1a62746](https://github.com/agentcontrol/agent-control/commit/1a627465a9266c6176f391e8f84f10304ba6a472))
* **ui:** add sql, luna2, json control forms and restructure the code ([#54](https://github.com/agentcontrol/agent-control/issues/54)) ([c4c1d4a](https://github.com/agentcontrol/agent-control/commit/c4c1d4ab53bce9bb9ee77657d4b9dd3152e587cd))
* **ui:** allow to delete control ([#39](https://github.com/agentcontrol/agent-control/issues/39)) ([7dc4ca3](https://github.com/agentcontrol/agent-control/commit/7dc4ca3e3d6b38c7cacfdabca18b28a0ed310b58))
* **ui:** Control Store Flow Updated ([#4](https://github.com/agentcontrol/agent-control/issues/4)) ([dda9f70](https://github.com/agentcontrol/agent-control/commit/dda9f70eb7b6e2bfa991ed71b270251ab51d3c9d))
* **ui:** stats dashboard ([#80](https://github.com/agentcontrol/agent-control/issues/80)) ([4cbb7fe](https://github.com/agentcontrol/agent-control/commit/4cbb7fee43ed14145815c9fd807b150f19200654))
* **ui:** Steps dropdown rendered based on api return values ([#36](https://github.com/agentcontrol/agent-control/issues/36)) ([a2aca43](https://github.com/agentcontrol/agent-control/commit/a2aca43979d6089969408c3ee29f53a749b5cf1c))
* **ui:** tests added and some minor ui changes, added error boundaries ([#61](https://github.com/agentcontrol/agent-control/issues/61)) ([009852b](https://github.com/agentcontrol/agent-control/commit/009852bb678d570d21de82fb1af89eececd2fdc8))
* **ui:** update agent control icon and favicon ([#42](https://github.com/agentcontrol/agent-control/issues/42)) ([19af8fa](https://github.com/agentcontrol/agent-control/commit/19af8faf26d5fb3dd895500f63108351cb77164b))

### Bug Fixes

* **ci:** Add ui scope to PR title validation ([#59](https://github.com/agentcontrol/agent-control/issues/59)) ([e0fdb52](https://github.com/agentcontrol/agent-control/commit/e0fdb528c201e15bab06668683ee02ef1dde70e8))
* **ci:** correct galileo contrib path in release build script ([#51](https://github.com/agentcontrol/agent-control/issues/51)) ([2de6013](https://github.com/agentcontrol/agent-control/commit/2de601338314b881f59847a5244b4226c74239f6))
* **ci:** Enable pr title on prs ([#56](https://github.com/agentcontrol/agent-control/issues/56)) ([3d8b5fe](https://github.com/agentcontrol/agent-control/commit/3d8b5fe8c21f1ffd7fd6f6bf4d4f4eaebbad9106))
* **ci:** Fix release ([#11](https://github.com/agentcontrol/agent-control/issues/11)) ([9dd3dd7](https://github.com/agentcontrol/agent-control/commit/9dd3dd795227f1d1db62e5ce2e8b336fe1c909f1))
* **ci:** Use galileo-automation bot for releases ([#57](https://github.com/agentcontrol/agent-control/issues/57)) ([bc8eea0](https://github.com/agentcontrol/agent-control/commit/bc8eea088c7e347daf8bc34eee528129ddb61d7f))
* **docs:** Add Example for Evaluator Extension ([#3](https://github.com/agentcontrol/agent-control/issues/3)) ([c2a70b3](https://github.com/agentcontrol/agent-control/commit/c2a70b335fb55481ad63b367ca87ba46de085343))
* **docs:** add setup script ([#49](https://github.com/agentcontrol/agent-control/issues/49)) ([7a212c3](https://github.com/agentcontrol/agent-control/commit/7a212c3d182ba3e07e56b0131957315b788f553a))
* **docs:** Clean up Protect  ([#76](https://github.com/agentcontrol/agent-control/issues/76)) ([99c16fd](https://github.com/agentcontrol/agent-control/commit/99c16fd8ed6620363f919818ebe4083f1489ba1c))
* **docs:** Fix Examples for LangGraph ([#64](https://github.com/agentcontrol/agent-control/issues/64)) ([23b30ae](https://github.com/agentcontrol/agent-control/commit/23b30ae1ddc5b878d8375b4f39a6617e7a0ae604))
* **docs:** Improve documentation for open source release ([#47](https://github.com/agentcontrol/agent-control/issues/47)) ([9018fb3](https://github.com/agentcontrol/agent-control/commit/9018fb3c79e385732957bafcf75dcec4f83b958d))
* **docs:** Remove old/unused examples ([#66](https://github.com/agentcontrol/agent-control/issues/66)) ([f417781](https://github.com/agentcontrol/agent-control/commit/f4177810579037a6c3f14cc4db59222166ec5209))
* **docs:** Update Contributing Guide ([#8](https://github.com/agentcontrol/agent-control/issues/8)) ([10b34c8](https://github.com/agentcontrol/agent-control/commit/10b34c8bd4a3502b7844bc6daded4a08fde50442))
* **docs:** Update readme  ([#37](https://github.com/agentcontrol/agent-control/issues/37)) ([7531d83](https://github.com/agentcontrol/agent-control/commit/7531d8309d4755d9ceddf4a2d840c147b36a6e14))
* **docs:** Update README ([#2](https://github.com/agentcontrol/agent-control/issues/2)) ([379bb15](https://github.com/agentcontrol/agent-control/commit/379bb158700b93aa549ef00eda57ccc2f88cb71f))
* **examples:** Control sets cleanup with signed ([#65](https://github.com/agentcontrol/agent-control/issues/65)) ([af7b5fb](https://github.com/agentcontrol/agent-control/commit/af7b5fb44fe800a98c617ee70ae258576e146115))
* **examples:** Update crew ai example to use evaluator ([#93](https://github.com/agentcontrol/agent-control/issues/93)) ([1c65084](https://github.com/agentcontrol/agent-control/commit/1c6508434860ed5bb56c622a721197c5a8f7ad4e))
* **infra:** Add plugins directory to Dockerfile ([#58](https://github.com/agentcontrol/agent-control/issues/58)) ([171d459](https://github.com/agentcontrol/agent-control/commit/171d459377aa294087f0af1561345a5e010120cb))
* **infra:** install engine/evaluators in server image ([#14](https://github.com/agentcontrol/agent-control/issues/14)) ([d5ae157](https://github.com/agentcontrol/agent-control/commit/d5ae1571071afd34a00b376e650d9e1ce02f0b2d))
* **models:** use StrEnum for error enums ([#12](https://github.com/agentcontrol/agent-control/issues/12)) ([3f41c9f](https://github.com/agentcontrol/agent-control/commit/3f41c9f974ba5afe873f30197aba7f2ff142f616))
* **sdk-ts:** add conventional commits preset dependency ([#55](https://github.com/agentcontrol/agent-control/issues/55)) ([540fe9d](https://github.com/agentcontrol/agent-control/commit/540fe9df8fc69f223218ef2defbcc662ab3a902a))
* **sdk-ts:** export npm token for semantic-release npm auth ([#54](https://github.com/agentcontrol/agent-control/issues/54)) ([1b6b993](https://github.com/agentcontrol/agent-control/commit/1b6b993eaed8c63ea4e61b21bc4fb27accaa2a49))
* **sdk:** 54253 add steer action and example ([#38](https://github.com/agentcontrol/agent-control/issues/38)) ([bf2380a](https://github.com/agentcontrol/agent-control/commit/bf2380aea5c879c77feb8f84a7fa14be5aa658b8))
* **sdk:** a bug in docker file ([#46](https://github.com/agentcontrol/agent-control/issues/46)) ([12d1794](https://github.com/agentcontrol/agent-control/commit/12d1794e3e7218eef10e371e12b001774bd81a68))
* **sdk:** Add step_name as parameter to control ([#25](https://github.com/agentcontrol/agent-control/issues/25)) ([19ade9d](https://github.com/agentcontrol/agent-control/commit/19ade9dcd69e264a62ccedf711722ef891d1b407))
* **sdk:** emit observability events for SDK-evaluated controls and fix non_matches propagation ([#24](https://github.com/agentcontrol/agent-control/issues/24)) ([6a9da69](https://github.com/agentcontrol/agent-control/commit/6a9da69aeb89a0a0a207f05fcbb03f1260faa40e))
* **sdk:** enforce UUID agent IDs ([#9](https://github.com/agentcontrol/agent-control/issues/9)) ([5ccdbd0](https://github.com/agentcontrol/agent-control/commit/5ccdbd04c73b50e86362ca3e4204cb0e84fa1b5c))
* **sdk:** Fix logging  ([#77](https://github.com/agentcontrol/agent-control/issues/77)) ([b1f078c](https://github.com/agentcontrol/agent-control/commit/b1f078c52c29ac048a9bcbea09252786e842acbd))
* **sdk:** plugin to evaluator.. agent_protect to agent_control ([#88](https://github.com/agentcontrol/agent-control/issues/88)) ([fc9b088](https://github.com/agentcontrol/agent-control/commit/fc9b088fcd091132a1e38deae372b73fc2834beb))
* **server:** enforce public-safe API error responses ([#20](https://github.com/agentcontrol/agent-control/issues/20)) ([e50d817](https://github.com/agentcontrol/agent-control/commit/e50d817e2b81347c9143dcae8d461e7e3e581fd9))
* **server:** Feature/56688 fix docker and create bash ([#45](https://github.com/agentcontrol/agent-control/issues/45)) ([7277e27](https://github.com/agentcontrol/agent-control/commit/7277e2730c16e717ad5ba8248b946252b22e69cb))
* **server:** Feature/56688 fix image bug ([#48](https://github.com/agentcontrol/agent-control/issues/48)) ([71e6b44](https://github.com/agentcontrol/agent-control/commit/71e6b44f3cdee26c7a97a2cfc0ef6223e52bdb3a))
* **server:** fix alembic migrations ([#47](https://github.com/agentcontrol/agent-control/issues/47)) ([c19c17c](https://github.com/agentcontrol/agent-control/commit/c19c17c6359b031bf5d69e81bfe72054bd09f40c))
* **server:** reject initAgent UUID/name mismatch ([#13](https://github.com/agentcontrol/agent-control/issues/13)) ([19d61ff](https://github.com/agentcontrol/agent-control/commit/19d61ff1e1605925162eca31bacbe35eddeb5c17))
* tighten evaluation error handling and preserve control data ([52a1ef8](https://github.com/agentcontrol/agent-control/commit/52a1ef8127aca382e373ee6b6433a2d527e6e5e2))
* **ui:** Fix UI and clients for simplified step schema ([#75](https://github.com/agentcontrol/agent-control/issues/75)) ([be2aaf0](https://github.com/agentcontrol/agent-control/commit/be2aaf0ae43a9051cb60ce3597f089307f731d0a))
* **ui:** json validation ([#10](https://github.com/agentcontrol/agent-control/issues/10)) ([a0cd5af](https://github.com/agentcontrol/agent-control/commit/a0cd5af4a05a01fa7e5f8824001659ebc6bee7bc))
* **ui:** selector subpaths issue ([#34](https://github.com/agentcontrol/agent-control/issues/34)) ([79cb776](https://github.com/agentcontrol/agent-control/commit/79cb776032cedfacac5f9480151acf184a9921a3))
* **ui:** UI feedback fixes ([#27](https://github.com/agentcontrol/agent-control/issues/27)) ([6004761](https://github.com/agentcontrol/agent-control/commit/60047619ccbd1876100a38e02537d6987d8a02f7))

### Code Refactoring

* **evaluators:** rename plugin to evaluator throughout  ([#81](https://github.com/agentcontrol/agent-control/issues/81)) ([0134682](https://github.com/agentcontrol/agent-control/commit/0134682c1d0f167528d7267507dbcf3a1e7b3192))
* **evaluators:** split into builtin + extra packages for PyPI ([#5](https://github.com/agentcontrol/agent-control/issues/5)) ([0e0a78a](https://github.com/agentcontrol/agent-control/commit/0e0a78a9fa9c39a5709299c2e3d77c0609110280))
* **models:** simplify step model and schema ([#70](https://github.com/agentcontrol/agent-control/issues/70)) ([4c1d637](https://github.com/agentcontrol/agent-control/commit/4c1d6378a4a05edc44f02fa78c1698b9203da81b))

# Changelog

All notable changes to the TypeScript SDK are documented in this file.
