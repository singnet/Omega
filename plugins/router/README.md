# Default router plugin

Uses [`default.metta`](default.metta) to choose between the `routine` and
`premium` LLM model roles before the harness sends a request to an LLM.
The router examines user messages and tool results, selecting a premium model
when its rules indicate that deeper reasoning may be needed. Otherwise, it
uses the routine model.

## How to use the default router

With `router=default` enabled, send `/premium` in chat to latch premium mode on.
Omega reports `Switching to the premium model.` Send `/routine` to clear that
override; the router's automatic rules can still select premium. Router logs
report `LLM: premium` or `LLM: routine` for the selected role.

<br>

## Default Router Design

The following numbered section describes the design of the default LLM router.

This design provides a starting point for custom router implementations.

### 1. The router catalog JSON file name is passed to Omega

The `routerCatalogFile` parameter specifies the path to the router catalog JSON
file:

```text
routerCatalogFile=/tmp/omega-router-catalog.json
```

The router catalog defines the provider and model combinations used for routine
and premium LLM calls. The following example illustrates the JSON structure
received by Omega proper:

```json
{
  "routine": {
    "provider": "OpenAI",
    "api_token_var": "OPENAI_API_KEY",
    "model": "gpt-6-luna",
    "openaiapi_url": ""
  },
  "premium": {
    "provider": "Anthropic",
    "api_token_var": "ANTHROPIC_API_KEY",
    "model": "claude-opus-5-5",
    "openaiapi_url": ""
  }
}
```

`provider` identifies the provider plugin,
`api_token_var` names the provider's API-key environment variable, and
`model` selects its model.
`openaiapi_url` supplies the endpoint when
`provider` is `OpenAIAPI`; other providers use their built-in endpoint.

### 2. The `router=default` parameter selects the default router

Omega selects the default router when its startup arguments include:

```text
router=default
```

This selects the default routing function. With `router=none`, the harness
bypasses routing and will use only the first entry in the router catalog, if any.
If no router catalog at all is found, Omega will build a router catalog with one entry
if it can find values for provider and model.

### 3. The plugin configuration registers the default router

The module is registered in [`config/plugins.yaml`](../../config/plugins.yaml):

```yaml
- name: default
  loader: metta
  location: "{REPO}/plugins/router"
```

This registration is already present in the repository. The plugin name
`default` corresponds to the file `default.metta` in that directory. The module
also provides the `loadOmegaPlugin` entry point required by the plugin loader.

### 4. The harness calls `default-LLM-ROUTER`

The function in `default.metta` has this signature; capitalization matters:

```metta
(= (default-LLM-ROUTER $prompt)
   ...)
```

When `router=default` is selected, the harness calls this function before each
LLM request routed through `llmProviderChat`.

The router name `default` is concatenated with the fixed suffix `-LLM-ROUTER`
to form `default-LLM-ROUTER`, the name of the default router's main routing
function. The router inputs some components of the imminent, staged prompt:  tool results and
new user messages. The router then outputs either premium or routine symbols. 
Omega, upon receipt of the decision, then looks up the result in the router catalog, stored internally in a MeTTa 
expression (not JSON), and calls the correct provider and model combination.

## HIDING TOKENS

### Docker mode

Automatic token hiding runs only through the Docker entry point:

1. The container initially receives `OMEGA_ROUTER_CATALOG` as an environment
   variable. EACH ROLE INCLUDES A `token` FIELD HOLDING ITS CREDENTIAL.
2. [`entrypoint.sh`](../../entrypoint.sh) reads and unsets
   `OMEGA_ROUTER_CATALOG` and then passes the secret credentials to the nginx
   proxy service through [`src/router_catalog.py`](../../src/router_catalog.py).
   The script also writes a catalog without `token` fields to
   `/tmp/omega-router-catalog.json`, which is input to Omega proper.
3. The entry point launches Omega as `nobody`, excluding API-key variables from
   its environment. Omega receives the sanitized catalog via `routerCatalogFile`
   and sends requests through nginx, which adds the credentials.

### Standalone mode

Standalone mode does not hide tokens from Omega:

1. The user must supply all required tokens individually as environment
   variables, separately from the catalog specified by `routerCatalogFile`.
   Their names must match each role's `api_token_var`, such as `OPENAI_API_KEY`
   and `ANTHROPIC_API_KEY`.
2. The catalog passed through `routerCatalogFile` variables without `token` fields.
3. With no `GATEWAY_URL` configured, providers read the tokens from Omega's
   environment and call their APIs directly.

## Creating your own router

In general, you can create your own router by copying the default router into
a new subdirectory under `plugins` and adapting the design described above.
Typically, you just replace `default` (as above) with your router's name in each step as defined above.

Importantly, you can devise new roles for your router to use. Each role must
have a matching entry in the router catalog specifying the desired provider and model combination as the above example shows. 
Your router must have an expression of this form to receive calls and then return the decided role identifier: 

`(= (name-of-your-router-LLM-ROUTER $prompt)
   ... decision logic... return decided role identifier)`

You are also able to create new skills as is allowed for any plugin.

