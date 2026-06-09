import os
dashboard_file = 'dashboard.html'
if not os.path.exists(dashboard_file):
    print('Error: dashboard.html not found.')
    exit(1)

with open(dashboard_file, 'r') as f: content = f.read()

resolver_js = """
function resolveMetric(data, path) {
    return path.split('.').reduce((prev, curr) => (prev && prev[curr] !== undefined) ? prev[curr] : undefined, data);
}

function updateMetrics(data) {
    const metrics = {
        'score': ['composite_score', 'evaluation.composite_score', 'evaluation.metrics.composite.score', 'score'],
        'stability': ['structural_stability', 'evaluation.metrics.structural_stability', 'structural_validity'],
        'efficiency': ['material_efficiency', 'evaluation.metrics.material_efficiency'],
        'simplicity': ['manufacturing_simplicity', 'evaluation.metrics.manufacturability']
    };

    for (const [id, keys] of Object.entries(metrics)) {
        let val = 'n/a';
        for (const key of keys) {
            let found = resolveMetric(data, key);
            if (found !== undefined) { val = found; break; }
        }
        const el = document.getElementById(id);
        if (el) el.innerText = (typeof val === 'number') ? val.toFixed(2) + '%' : val;
    }
}
"""

marker = '// --- SOCKET EVENT HANDLERS ---'
if marker in content and 'resolveMetric' not in content:
    content = content.replace(marker, marker + '\\n' + resolver_js)
    with open(dashboard_file, 'w') as f: f.write(content)
    print("Successfully patched dashboard.html")
else:
    print("Patch already applied or marker not found.")
