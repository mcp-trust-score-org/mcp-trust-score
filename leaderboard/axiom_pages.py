"""Pages HTML de l'audit AXIOM v1.1 : formulaire, bilan, méthodologie publique."""

BASE_CSS = """
    * { box-sizing: border-box; }
    body { font-family: 'Segoe UI', -apple-system, Arial, sans-serif; max-width: 880px; margin: 0 auto;
           padding: 0 20px 60px; color: #1e293b; background: #f8fafc; }
    .nav { padding: 20px 0; }
    .nav a { color: #475569; margin-right: 20px; text-decoration: none; font-size: 14px; font-weight: 500; }
    .nav a:hover { color: #2563eb; }
    .header { background: linear-gradient(135deg, #0f172a, #1e293b); color: white; padding: 32px;
              border-radius: 12px; margin-bottom: 28px; }
    .header h1 { margin: 0 0 8px; font-size: 24px; }
    .header p { margin: 4px 0 0; color: #cbd5e1; font-size: 14px; }
    .card { background: white; border-radius: 12px; padding: 24px 28px; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            margin-bottom: 18px; }
    .domain-title { font-size: 17px; font-weight: 700; color: #0f172a; margin: 32px 0 12px; padding-bottom: 8px;
                    border-bottom: 2px solid #e2e8f0; }
    .tag { display: inline-block; background: #eff6ff; color: #1d4ed8; font-size: 11px; font-weight: 700;
           padding: 3px 10px; border-radius: 6px; margin-bottom: 8px; }
    .tag.measured { background: #fef3c7; color: #92400e; }
    .muted { color: #64748b; font-size: 13px; }
    .bp { white-space: pre-line; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .scroll { overflow-x: auto; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
    th { background: #f1f5f9; font-weight: 600; }
    details summary { cursor: pointer; color: #2563eb; font-size: 13px; margin: 8px 0; }
    .rules { white-space: pre-line; font-size: 13px; color: #334155; background: #f8fafc; padding: 10px 12px;
             border-radius: 8px; }
    @media (max-width: 640px) { .row { flex-direction: column; } body { padding: 0 12px 40px; }
      .card { padding: 16px; } .nav a { display: inline-block; margin: 0 12px 6px 0; } }
"""

NAV = """<div class="nav"><a href="/">🏆 Classement</a><a href="/audit">🔍 Audit organisationnel</a>
<a href="/companies">🏅 Entreprises évaluées</a><a href="/methodologie">📐 Méthodologie</a></div>"""

LEVEL_OPTIONS = """<option value="">— choisir —</option><option value="N/A">N/A (non évalué)</option>
{% for v in levels %}<option value="{{ v }}">{{ '%g' % v }}{% if v == v|int %} — {{ labels[v|int] }}{% endif %}</option>{% endfor %}"""

AUDIT_FORM_V11 = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Audit AXIOM — MCP Trust Score</title>
  <style>""" + BASE_CSS + """
    label.f { font-weight: 600; font-size: 13px; color: #334155; display: block; margin: 0 0 6px; }
    input[type=text], input[type=password], select, textarea { width: 100%; padding: 9px 12px; border-radius: 8px;
      border: 1px solid #cbd5e1; font-size: 14px; font-family: inherit; margin-bottom: 14px; }
    textarea { min-height: 60px; resize: vertical; font-size: 13px; }
    .row { display: flex; gap: 14px; }
    .row > div { flex: 1; }
    .levels { font-size: 13px; margin: 8px 0 12px; padding-left: 0; list-style: none; }
    .levels li { padding: 4px 0; border-bottom: 1px dashed #e2e8f0; }
    .levels b { display: inline-block; width: 26px; color: #1d4ed8; }
    .submit-btn { background: #0f172a; color: white; border: none; padding: 14px 28px; border-radius: 10px;
      font-size: 15px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 16px; }
    .submit-btn:disabled { background: #94a3b8; }
  </style>
</head>
<body>
""" + NAV + """
  <div class="header">
    <h1>Audit — {{ version }}</h1>
    <p>{{ n }} sous-domaines, 9 domaines. Pour chaque sous-domaine : niveau proposé, type de preuve obtenue, justification.</p>
    <p>Le niveau retenu est plafonné par la preuve (voir la <a href="/methodologie" style="color:#93c5fd">méthodologie</a>).
       Un sous-domaine non évalué compte comme N/A et réduit la couverture.</p>
  </div>

  <form id="auditForm">
    <div class="card">
      <label class="f">Entreprise évaluée</label>
      <input type="text" id="companyName" required maxlength="200">
      <label class="f">Repo MCP lié (optionnel — éligibilité Platinum)</label>
      <input type="text" id="linkedRepo" placeholder="https://github.com/owner/repo">
      <p class="muted">Connecté en tant qu'évaluateur : <b>{{ auditor }}</b>. Grille confidentielle — ne pas diffuser.</p>
    </div>

    {% for s in subs %}
    {% if loop.first or s.domain != subs[loop.index0 - 1].domain %}<div class="domain-title">{{ s.domain }}</div>{% endif %}
    <div class="card" data-id="{{ s.id }}">
      <span class="tag">{{ s.id }}</span>
      {% if s.measured_required_from_n3 %}<span class="tag measured">Mesure technique exigée au-delà de N2</span>{% endif %}
      <p style="font-weight:600;margin:4px 0 6px">{{ s.title }}</p>
      <p class="muted bp" style="margin:0 0 6px">{{ s.good_practice | trim }}</p>
      <ul class="levels">{% for t in s.levels %}<li><b>N{{ loop.index0 }}</b>{{ t }}</li>{% endfor %}</ul>
      <details><summary>Preuves attendues</summary><div class="rules">{{ s.evidence_rules }}</div></details>
      <div class="row">
        <div><label class="f">Niveau proposé</label><select class="lvl">""" + LEVEL_OPTIONS + """</select></div>
        <div><label class="f">Type de preuve obtenue</label><select class="ev"><option value="">— choisir —</option>
          {% for e in evidence_types %}<option value="{{ e.name }}">{{ e.name }} (max {{ e.max_level }})</option>{% endfor %}</select></div>
      </div>
      <label class="f">Justification / sources</label>
      <textarea class="just" maxlength="2000" placeholder="Document, page, date d'entretien, rapport de test…"></textarea>
    </div>
    {% endfor %}

    <button type="submit" class="submit-btn" id="submitBtn">Calculer et enregistrer le bilan</button>
  </form>

  <script>
    document.getElementById('auditForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('submitBtn');
      const entries = [];
      for (const card of document.querySelectorAll('[data-id]')) {
        const lvl = card.querySelector('.lvl').value;
        if (!lvl) continue;
        entries.push({
          id: card.dataset.id,
          level: lvl === 'N/A' ? 'N/A' : parseFloat(lvl),
          evidence: card.querySelector('.ev').value || null,
          justification: card.querySelector('.just').value,
        });
      }
      btn.disabled = true; btn.textContent = 'Calcul du bilan…';
      const res = await fetch('/submit-audit', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          company_name: document.getElementById('companyName').value,
          linked_repo_url: document.getElementById('linkedRepo').value,
          entries: entries,
        }),
      });
      const data = await res.json();
      if (res.ok) { window.location.href = data.report_url; }
      else { alert('Erreur : ' + (data.error || 'inconnue')); btn.disabled = false; btn.textContent = 'Calculer et enregistrer le bilan'; }
    });
  </script>
</body>
</html>
"""

AUDIT_REPORT_V11 = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bilan AXIOM — {{ company_name }}</title>
  <style>""" + BASE_CSS + """
    .tier { display: inline-block; padding: 7px 18px; border-radius: 20px; font-weight: 700; margin-top: 12px; }
    .tier-Platinum { background: #ede9fe; color: #6d28d9; } .tier-Gold { background: #fef3c7; color: #92400e; }
    .tier-none { background: #fee2e2; color: #991b1b; }
    .kpis { display: flex; gap: 16px; flex-wrap: wrap; }
    .kpi { flex: 1; min-width: 130px; }
    .kpi .v { font-size: 34px; font-weight: 800; color: #0f172a; }
    .capped { color: #b45309; font-size: 12px; }
    .lvl { font-weight: 700; white-space: nowrap; }
    .radar { text-align: center; }
  </style>
</head>
<body>
""" + NAV + """
  <div class="header">
    <h1>{{ company_name }}</h1>
    <p>Évalué le {{ audited_at }} par {{ auditor }} — méthode {{ r.methodology }}</p>
    <span class="tier tier-{{ tier }}">{{ {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold'}.get(tier, '— Aucun palier') }}</span>
    <p>{{ tier_reason }}</p>
  </div>

  <div class="card kpis">
    <div class="kpi"><div class="v">{{ '%.1f' % r.score if r.score is not none else '—' }} %</div><div class="muted">Score (sous-domaines évalués)</div></div>
    <div class="kpi"><div class="v">{{ '%.1f' % r.coverage }} %</div><div class="muted">Couverture pondérée</div></div>
    <div class="kpi"><div class="v">{{ r.evaluated }} / {{ r.total }}</div><div class="muted">Sous-domaines évalués</div></div>
    <div class="kpi"><div class="v">{{ r.capped_count }}</div><div class="muted">Niveaux plafonnés faute de preuve</div></div>
  </div>

  <div class="card radar"><h3 style="margin-top:0">Score par domaine</h3>{{ radar_svg | safe }}</div>

  <div class="card scroll">
    <table>
      <tr><th>Domaine</th><th>Score</th><th>Couverture</th></tr>
      {% for d, v in r.domains.items() %}
      <tr><td>{{ d }}</td><td>{{ '%.0f %%' % v.score if v.score is not none else 'non évalué' }}</td>
          <td>{{ '%.0f %%' % v.coverage if v.coverage is not none else '—' }}</td></tr>
      {% endfor %}
    </table>
  </div>

  <div class="card scroll">
    <h3 style="margin-top:0">Détail</h3>
    <table>
      <tr><th>Sous-domaine</th><th>Proposé</th><th>Preuve</th><th>Retenu</th><th>Justification</th></tr>
      {% for d in r.details if d.level is not none %}
      <tr>
        <td><b>{{ d.id }}</b> {{ d.title }}</td>
        <td class="lvl">{{ '%g' % d.level }}</td>
        <td>{{ d.evidence or 'aucune' }}</td>
        <td class="lvl">{{ '%g' % d.retained }}{% if d.label %} — {{ d.label }}{% endif %}
            {% if d.capped %}<div class="capped">{{ d.capped }}</div>{% endif %}</td>
        <td class="muted">{{ d.justification }}</td>
      </tr>
      {% endfor %}
    </table>
    {% set na = r.details | selectattr('level', 'none') | list %}
    {% if na %}<p class="muted">Non évalués : {% for d in na %}{{ d.id }}{{ ', ' if not loop.last }}{% endfor %}.</p>{% endif %}
  </div>

  <div class="card muted">
    Évaluation réalisée par {{ auditor }} selon la méthode {{ r.methodology }}
    (<a href="/methodologie">méthodologie publique</a>). Chaque niveau retenu est plafonné par le type de preuve
    obtenue ; le score porte sur les sous-domaines évalués et doit être lu avec sa couverture.
    Les correspondances avec d'autres référentiels sont indicatives : ce bilan n'est pas une certification.
  </div>
</body>
</html>
"""

METHODOLOGY_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Méthodologie {{ version }} — MCP Trust Score</title>
  <style>""" + BASE_CSS + """</style>
</head>
<body>
""" + NAV + """
  <div class="header">
    <h1>Méthodologie {{ version }}</h1>
    <p>Principes appliqués à toutes les évaluations : mêmes règles pour tous.</p>
  </div>

  <div class="card">
    <h3 style="margin-top:0">Règles d'évaluation</h3>
    <ul>
      <li>Chaque sous-domaine est évalué de 0 ({{ labels[0] }}) à 4 ({{ labels[4] }}), demi-niveaux possibles.
          Les niveaux sont cumulatifs.</li>
      <li>Chaque niveau s'appuie sur une preuve ; le niveau retenu ne dépasse jamais le plafond du type de
          preuve obtenue (tableau ci-dessous).</li>
      <li>Pour les sous-domaines marqués « mesure technique », seule une mesure réalisée par l'évaluateur permet
          de dépasser N{{ measured_cap }}.</li>
      <li>Score = Σ(niveau retenu × pondération) ÷ Σ(4 × pondération), sur les sous-domaines évalués.
          La couverture pondérée est toujours publiée avec le score.</li>
      <li>Palier Gold : score ≥ {{ gold_min|int }} % avec une couverture ≥ {{ coverage_min|int }} %.
          Platinum : Gold + palier technique Silver d'un dépôt lié.</li>
      <li>Le détail de la grille (description des niveaux, preuves attendues, pondérations) est remis à
          l'organisation évaluée dans le cadre de l'audit.</li>
    </ul>
    <div class="scroll"><table>
      <tr><th>Type de preuve</th><th>Niveau maximum</th><th></th></tr>
      {% for e in evidence_types %}<tr><td>{{ e.name }}</td><td>{{ e.max_level }}</td><td class="muted">{{ e.description }}</td></tr>{% endfor %}
    </table></div>
  </div>

  <div class="card">
    <h3 style="margin-top:0">Périmètre : {{ n }} sous-domaines</h3>
    {% for s in subs %}
    {% if loop.first or s.domain != subs[loop.index0 - 1].domain %}<p style="font-weight:700;margin:16px 0 6px">{{ s.domain }}</p>{% endif %}
    <p style="margin:2px 0">{{ s.id }} — {{ s.title }}{% if s.measured_required_from_n3 %} <span class="tag measured">mesure technique</span>{% endif %}</p>
    {% endfor %}
  </div>

  <div class="card muted">Une évaluation AXIOM n'est pas une certification. Les correspondances avec d'autres
    référentiels sont indicatives.</div>
</body>
</html>
"""
