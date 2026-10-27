# 01 — A plugin's tools can be granted, and declare their effect

**Filed:** [lbedner/aegis-stack#1868](https://github.com/lbedner/aegis-stack/issues/1868) - tracker #1872

**Repo:** `aegis-stack` (framework) · **Blocks:** 22

## Why

A plugin's `tools.py` is discovered by convention, and then two walls:

1. `app/services/ai/domains/chat/agent_loader.py.jinja` grants the seeded
   agent a **static tuple** of tool names. A plugin's tool is registered and
   ungranted: the agent cannot use what it was never told about.
2. `tests/core/test_tools.py` keeps `EXPECTED_EFFECTS` as a static dict in
   a **shared template file** and asserts every registered app tool appears
   in it. Adding a tool from a plugin fails that generated project's test,
   and a plugin may not patch a shared file (`post_render`'s own docstring
   confines hooks to manifest-owned paths).

This is why `aegis-stack-media` ships no `tools.py` today: a tool nobody can
grant, which breaks the project's own suite, is worse than no tool.

## Scope

- `PluginWiring.agent_tools: list[AgentToolWiring]` (name + effect), read by
  the plugin composer into the answers file.
- `agent_loader.default_agent_config()` appends the plugins' tools to
  `tool_names` (after the in-tree ones, before the seeded row is written).
- The tool-effect bookkeeping reads the registry rather than a hand-kept
  dict, **or** the generated `EXPECTED_EFFECTS` is extended from the answers'
  plugin tool entries — whichever keeps the "every tool's effect is a
  decision" guarantee.
- `docs/plugins/creating.md`: the convention table row for `tools.py` gains
  the grant; a `wiring` example lands in the scaffold's `plugin.py`.

## Done when

- A test plugin that registers `register_tool("echo", effect="read")` is
  added to a scratch stack, and that stack's `tests/core/test_tools.py` and
  the seeded agent both pass with the tool granted.
- The same plugin's tool is **not** granted when the class of tool is not
  declared (no accidental blanket grant).
- `tests/core/test_plugin_wiring.py`-style pins exist for the new field.
