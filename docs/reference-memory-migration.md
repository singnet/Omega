# Reference - Memory Migration

## Recovering an interrupted memory migration

When upgrading from OmegaClaw, the launcher copies `omegaclaw-memory` to
`omega-memory`. Keep the terminal open and do not interrupt the launcher or
Docker until it reports `Memory copied`. Keep `omegaclaw-memory` until you have
checked that the agent remembers its previous data.

If the copy is interrupted, follow the appropriate path below before importing
memory or starting the agent again. Use the same image tag and launcher options
as in your original start command.

### Retry the copy from OmegaClaw

Use this path only if `omega-memory` contains no imported memory or new agent
data that you need to keep. Retrying replaces this volume with a fresh copy of
`omegaclaw-memory`.

1. List the containers holding the destination volume:

   ```sh
   docker ps -a --filter volume=omega-memory --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}'
   ```

2. If the launcher reports `volume is in use` or names a leftover container,
   stop and remove the identified container. Replace `CONTAINER_ID` with its
   actual ID; do not remove unrelated containers or the source volume:

   ```sh
   docker rm -f CONTAINER_ID
   ```

   This also applies to stopped containers. Copy containers started by the
   v0.1.20 launcher have no migration label and need to be removed manually.
   The updated launcher removes labelled copy containers and the `omega`
   container automatically when retrying.

3. Repeat your original `scripts/omega start ...` command, without
   `--memory-import` or the `--only-history` and `--only-vector` flags. Wait for
   `Memory copied`, then check the agent's memory.

### Keep memory imported or used after the interruption

Do not retry the copy or run another import before preserving the current
`omega-memory` volume. Stop any remaining copy containers identified above and
stop the `omega` agent if it is running. Back up the destination volume before
changing migration state.

The v0.1.20 launcher could leave `.migration-started` in `omegaclaw-memory`
after a memory import. In particular, an `--only-vector` import can leave
`history.metta` unchanged. The updated launcher's history check cannot detect
this case: a normal start can delete the imported vectors and copy the old
memory over them.

If the import completed successfully and you want to keep the current memory,
clear only the stale migration marker before starting again:

```sh
docker volume inspect omegaclaw-memory omega-memory
docker run --rm --entrypoint rm --volume omegaclaw-memory:/from \
  singularitynet/omega:v0.1.20 -f /from/.migration-started
```

Run the second command only if both volumes exist. Then repeat your normal
start command without `--memory-import` or the `--only-history` and
`--only-vector` flags. Clearing the marker keeps the current destination volume;
it does not finish a partial copy. If you are unsure whether
the import or copy completed, preserve both volumes and ask for help before
continuing.

If imported memory has already been overwritten, the old OmegaClaw volume
cannot recover that import. Restore it from the original import archive or a
backup of `omega-memory`.

