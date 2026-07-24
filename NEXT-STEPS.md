# Next steps — from this code to production

Ordered checklist to get Triagebox running on its VM and wired into your
workflow. Steps marked **(interactive)** require login/authorization and
you have to run them yourself (from Claude Code you can launch them with
the `!` prefix so the output lands in the conversation).

Background reference: `Duna/docs/inbox/00-plan-inbox.md` (plan) and
`Duna/docs/inbox/01-integracion-duna.md` (integration, at the end).

---

## 1. Repo on GitHub

Done — the initial commit was created and pushed to
`https://github.com/erico089dev/triagebox` (public).

## 2. Create the VM on GCP — phase F0  (interactive)

```bash
gcloud auth login                       # if needed
gcloud config get-value project         # confirm the project

gcloud compute instances create triagebox-vm \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard
```

Reminders (plan §3): explicit `pd-standard` (the default isn't free tier),
free-tier zone, and **don't** open inbound ports — only `default-allow-ssh`
should exist. Expected cost: ~$7–10/month (2nd micro + IPv4); check
Billing → Reports after a few days.

## 3. Base VM setup  (the Tailscale step is interactive)

Log in: `gcloud compute ssh triagebox-vm --zone=us-central1-a`

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install git python3-venv sqlite3

# 2 GB swap (required with 1 GB RAM):
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile \
  && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tailscale (same account as duna-vm):
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname=triagebox-vm
# → open the printed URL and authorize the machine  (interactive)
tailscale ip -4
```

## 4. Install Triagebox on the VM

```bash
cd ~ && git clone https://github.com/erico089dev/triagebox.git && cd triagebox
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-transcribe.txt

cp .env.example .env
nano .env            # WHISPER_ENABLED=true, WHISPER_MODEL=base — the rest is fine as-is

cp apps.yml.example apps.yml && chmod 600 apps.yml
openssl rand -hex 24   # run it twice → capture token and dev token
nano apps.yml          # paste the real tokens for the duna app
```

Systemd service (adjust the user if your `$USER` isn't `triagebox`):

```bash
sed -e "s/User=triagebox/User=$USER/" -e "s#/home/triagebox#$HOME#g" \
  infra/triagebox.service | sudo tee /etc/systemd/system/triagebox.service
sudo systemctl daemon-reload && sudo systemctl enable --now triagebox
curl -s http://127.0.0.1:8080/api/health     # → {"status":"ok",...}
```

## 5. Expose over HTTPS on the tailnet

Requires MagicDNS + HTTPS Certificates already enabled in the Tailscale
admin console (you did this for Duna; if not:
<https://login.tailscale.com/admin/dns>).

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
sudo tailscale serve status
```

## 6. Test (F0–F2 "done" criteria)

- [ ] From the PC: `curl https://triagebox-vm.<tailnet>.ts.net/api/health` → ok.
- [ ] From the iPhone (Tailscale on): same URL in Safari → ok.
- [ ] **Negative test:** with Tailscale off on PC/iPhone, the URL does
      **not** respond.
- [ ] Create a text ticket with the capture token (curl) and list it with
      the dev token.
- [ ] The capture token gets **403** when listing (`GET /api/tickets`).
- [ ] Send a short audio clip and check that after a bit it has
      `transcript` and `transcript_status: "done"`. (The first transcription
      takes longer: it downloads the model. If Spanish/Catalan quality
      isn't good enough, try `WHISPER_MODEL=small` while watching RAM; if
      it's tight, go back to `base` or consider an external API — plan
      §4.6.)

## 7. iOS Shortcut (the star capture tool)

In Shortcuts, create "Report Duna":

1. **Record Audio** (stop on tap).
2. **Get Contents of URL**:
   - URL: `https://triagebox-vm.<tailnet>.ts.net/api/reports`
   - Method: POST · Body: **Form**
   - Fields: `audio` = (recorded audio) · `channel` = `ios-shortcut`
   - Header: `Authorization` = `Bearer <capture-token>`
3. **Show Result** (optional, to see the ticket id).
4. Add it to the home screen / action button. Duplicate the shortcut with
   **Ask for Input** instead of recording for the text variant.

## 8. Backup

```bash
crontab -e     # add:
0 4 * * * /home/YOUR_USER/triagebox/infra/backup.sh
```

## 9. Wire up the Claude Code skill in Duna

The skill already exists at `Duna/.claude/skills/tickets/SKILL.md`. It just
needs credentials: in the `.env` at the **root of the Duna repo on your
PC** (gitignored — never on the Duna VM):

```bash
TRIAGEBOX_URL=https://triagebox-vm.<tailnet>.ts.net
TRIAGEBOX_DEV_TOKEN=<token with read,write>
```

Test: send a report via the shortcut, then in Claude Code (Duna repo) say
**"check the new tickets"** — it should list it, propose a triage, and
mark it `triaged` on confirmation. With that, the street → home loop is
closed.

## 10. Full Duna integration (phase F4 — with Claude)

Once everything above works, follow
`Duna/docs/inbox/01-integracion-duna.md`: `POST /api/report` on the
backend, `/bug` on the Telegram bot, a text button in the PWA, and its
verification checklist.
