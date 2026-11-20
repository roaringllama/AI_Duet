# AI_Duet

Link two local LLMs together and watch them collaborate on problem solving.

Two servers (Ollama or Lemonade, via the Ollama-style `/api/chat`) take turns replying to each other. Each side keeps its own history. You get a live desktop window and a browser page where you set up and watch the run.

Python standard library only (tkinter for the window).

## Run

```bash
py ollama-duet-v7.py --remote http://FRIEND_TAILSCALE_IP:13305 --serve-host YOUR_TAILSCALE_IP --wait
```

Then open `http://YOUR_TAILSCALE_IP:8080`. Set the starting prompt, turns, model and system prompt per side (or one shared prompt), an optional stop rule, and press Start.

## Options

`--local`, `--local-model`, `--remote` (required), `--remote-model`, `--topic`, `--turns`, `--system-local`, `--system-remote`, `--same-prompt`, `--topic-both`, `--stop-pattern`, `--stop-side`, `--serve-host`, `--serve-port`, `--wait`, `--no-gui`.

- System prompts are optional. Empty means none is sent.
- `--topic-both` also shows the starting prompt to Side B.

## Security

The control page has no login. Anyone who can reach it can start runs on both servers. Bind `--serve-host` to a private address such as a Tailscale IP, never `0.0.0.0` on an untrusted network.

## License

GPL-3.0. See `LICENSE`.
