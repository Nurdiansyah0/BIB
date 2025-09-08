// static/app.js
// Frontend helpers for the Inspection Form page
// - Populates terminal dropdown from /api/terminals
// - Fetches terminal form_schema and renders dynamic fields
// - Captures geolocation and verifies via /api/verify-location
// - Submits data (best-effort). If server endpoint is missing, shows a friendly message.

(function () {
  const form = document.getElementById('inspectionForm');
  if (!form) return; // Loaded on other pages; no-op

  const selTerminal = document.getElementById('terminal');
  const formArea = document.getElementById('formArea');
  const btnGeo = document.getElementById('btnGeo');
  const geoNote = document.getElementById('geoNote');
  const statusEl = document.getElementById('status');
  const latEl = document.getElementById('lat');
  const lonEl = document.getElementById('lon');

  function setStatus(msg, ok = false) {
    if (!statusEl) return;
    statusEl.style.color = ok ? 'lime' : 'yellow';
    statusEl.textContent = msg;
  }

  // Track current bulk submit handler to avoid duplicate listeners
  let bulkSubmitHandler = null;

  // Render full checklist of items for selected area (no dropdown)
  async function renderItemsChecklist(lid) {
    const areaEl = formArea.querySelector('#field_Area');
    if (!areaEl || !lid) return;
    try {
      const areas = await fetchJSON(`/api/lokasi/${encodeURIComponent(lid)}/areas`);
      const found = areas.find(a => a.nama_area === areaEl.value);
      if (!found) return;
      const items = await fetchJSON(`/api/area/${encodeURIComponent(found.id_area)}/items`);
      // Hide single-item dropdown and global status when showing checklist
      const itemWrapExisting = formArea.querySelector('#field_Item_Cek_ID')?.parentElement;
      if (itemWrapExisting) itemWrapExisting.style.display = 'none';
      const statusGroup = formArea.querySelector('#status_group');
      if (statusGroup) statusGroup.remove();
      let box = document.getElementById('itemsChecklist');
      if (!box) {
        box = document.createElement('div');
        box.id = 'itemsChecklist';
        const h = document.createElement('h3'); h.textContent = 'Daftar Item'; box.appendChild(h);
        const shiftRow = document.createElement('div'); shiftRow.className='row';
        const shiftLabel = document.createElement('label'); shiftLabel.textContent='Shift'; shiftRow.appendChild(shiftLabel);
        const shiftSel = document.createElement('select'); shiftSel.id='shift_sel'; ['Pagi','Siang','Malam'].forEach(s=>{ const o=document.createElement('option'); o.value=s; o.textContent=s; shiftSel.appendChild(o); });
        shiftRow.appendChild(shiftSel); box.appendChild(shiftRow);
        formArea.appendChild(box);
      } else {
        box.innerHTML = '<h3>Daftar Item</h3>';
        const shiftRow = document.createElement('div'); shiftRow.className='row';
        shiftRow.innerHTML = '<label>Shift</label>';
        const shiftSel = document.createElement('select'); shiftSel.id='shift_sel'; ['Pagi','Siang','Malam'].forEach(s=>{ const o=document.createElement('option'); o.value=s; o.textContent=s; shiftSel.appendChild(o); });
        shiftRow.appendChild(shiftSel); box.appendChild(shiftRow);
      }
      items.forEach(it => {
        const row = document.createElement('div'); row.className='row';
        const label = document.createElement('label'); label.textContent = it.nama_item; label.style.fontWeight='bold';
        const group = document.createElement('div');
        const good = document.createElement('input'); good.type='radio'; good.name=`st_${it.id_item}`; good.value='Bagus'; good.checked=true;
        const lg = document.createElement('span'); lg.textContent=' Baik '; lg.style.marginRight='12px';
        const bad = document.createElement('input'); bad.type='radio'; bad.name=`st_${it.id_item}`; bad.value='Rusak';
        const lb = document.createElement('span'); lb.textContent=' Rusak ';
        const note = document.createElement('textarea'); note.placeholder='Keterangan kerusakan'; note.rows=2; note.style.display='none'; note.id=`note_${it.id_item}`;
        function sync(){ note.style.display = bad.checked ? 'block':'none'; }
        good.addEventListener('change', sync); bad.addEventListener('change', sync);
        group.appendChild(good); group.appendChild(lg); group.appendChild(bad); group.appendChild(lb);
        row.appendChild(label); row.appendChild(group); row.appendChild(note);
        box.appendChild(row);
      });
      // Attach submit handler to bulk send (deduplicate listener)
      form.removeEventListener('submit', submitInspection);
      if (bulkSubmitHandler) {
        form.removeEventListener('submit', bulkSubmitHandler);
      }
      bulkSubmitHandler = (e) => submitBulkInspections(e, lid, found.id_area);
      form.addEventListener('submit', bulkSubmitHandler);
    } catch (e) {
      console.warn('renderItemsChecklist', e);
    }
  }

  async function submitBulkInspections(e, lid, areaId) {
    e.preventDefault();
    setStatus('Mengirim data inspeksi...');
    const lat = Number(latEl.value), lon = Number(lonEl.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) { setStatus('Ambil lokasi terlebih dahulu.', false); return; }
    // Build items
    const rows = [];
    const radios = formArea.querySelectorAll('input[type="radio"][name^="st_"]');
    const names = new Set(); radios.forEach(r=>names.add(r.name));
    for (const n of names) {
      const id = Number(n.slice(3));
      const chosen = formArea.querySelector(`input[name="${n}"]:checked`);
      const status = chosen ? chosen.value : 'Bagus';
      const catatan = formArea.querySelector(`#note_${id}`)?.value || null;
      if (status === 'Rusak' && !(catatan && catatan.trim())) { setStatus('Isi keterangan kerusakan untuk item rusak.', false); return; }
      rows.push({ item_id: id, status, catatan });
    }
    const shift = document.getElementById('shift_sel')?.value || null;
    try {
      const res = await fetch('/api/inspections/bulk-normalized', {
        method: 'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ lokasi_id: lid, area_id: areaId, shift, lat, lon, items: rows })
      });
      const data = await res.json().catch(()=>({}));
      if(!res.ok) throw new Error(data.detail || 'Gagal menyimpan');
      setStatus(`Tersimpan ${data.created} baris.`, true);
      form.reset(); clearFormArea();
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }
  function setGeoNote(msg, ok = false) {
    if (!geoNote) return;
    geoNote.style.color = ok ? 'lime' : 'yellow';
    geoNote.textContent = msg;
  }

  async function fetchJSON(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data && (data.detail || data.message);
      throw new Error(detail || `${res.status} ${res.statusText}`);
    }
    return data;
  }

  async function loadTerminals() {
    try {
      selTerminal.innerHTML = '<option value="">Memuat...</option>';
      const list = await fetchJSON('/api/terminals');
      selTerminal.innerHTML = '<option value="">— Pilih Terminal —</option>';
      (list || []).forEach((t) => {
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.textContent = t.name;
        selTerminal.appendChild(opt);
      });
    } catch (err) {
      selTerminal.innerHTML = '<option value="">Gagal memuat terminal</option>';
      try { notify('Gagal memuat daftar terminal', 'error'); } catch(_) {}
    }
  }

  function clearFormArea() {
    formArea.innerHTML = '';
  }

  function createFieldEl(field) {
    const wrap = document.createElement('div');
    wrap.className = 'row';

    const label = document.createElement('label');
    label.htmlFor = `field_${field.name}`;
    label.textContent = field.label || field.name;

    let input;
    const type = (field.type || 'text').toLowerCase();
    if (type === 'select' && Array.isArray(field.options)) {
      input = document.createElement('select');
      field.options.forEach((opt) => {
        const o = document.createElement('option');
        if (typeof opt === 'object') {
          o.value = opt.value ?? opt.id ?? String(opt);
          o.textContent = opt.label ?? opt.name ?? String(opt.value ?? opt);
        } else {
          o.value = String(opt);
          o.textContent = String(opt);
        }
        input.appendChild(o);
      });
    } else if (type === 'textarea') {
      input = document.createElement('textarea');
      input.rows = 3;
    } else if (type === 'checkbox') {
      input = document.createElement('input');
      input.type = 'checkbox';
    } else if (type === 'number') {
      input = document.createElement('input');
      input.type = 'number';
      if (field.step != null) input.step = field.step;
      if (field.min != null) input.min = field.min;
      if (field.max != null) input.max = field.max;
    } else {
      input = document.createElement('input');
      input.type = type;
    }

    input.id = `field_${field.name}`;
    input.name = field.name;
    input.dataset.fieldName = field.name;
    if (field.placeholder) input.placeholder = field.placeholder;
    if (field.required) input.required = true;
    if (field.value != null) input.value = field.value;

    wrap.appendChild(label);
    wrap.appendChild(input);
    return wrap;
  }

  async function loadOptionsFromDB(terminalId, fields) {
    if (!terminalId || !fields.length) return {};
    const params = new URLSearchParams();
    fields.forEach((f) => params.append('field', f));
    const url = `/api/terminals/${encodeURIComponent(terminalId)}/options?${params.toString()}`;
    try {
      const data = await fetchJSON(url);
      return data || {};
    } catch (e) {
      try { notify('Gagal memuat opsi', 'warn'); } catch(_) {}
      return {};
    }
  }

  function normalizeSchema(schema) {
    // Accept common shapes: { fields: [...] } OR [...] OR {name: type, ...}
    if (!schema) return [];
    if (Array.isArray(schema)) return schema;
    if (Array.isArray(schema.fields)) return schema.fields;
    if (typeof schema === 'object') {
      return Object.keys(schema).map((k) => ({ name: k, label: k, type: schema[k] || 'text' }));
    }
    return [];
  }

  async function renderFormSchema(schema) {
    clearFormArea();
    const fields = normalizeSchema(schema);
    if (!fields.length) {
      const p = document.createElement('p');
      p.className = 'note';
      p.textContent = 'Skema form belum tersedia untuk terminal ini.';
      formArea.appendChild(p);
      return;
    }

    // Ensure specific fields are dropdowns populated from DB
    const SPECIAL_FIELDS = ['Lokasi', 'ID_Lokasi', 'Area', 'Item_Cek_ID'];
    const terminalId = selTerminal.value;
    const needOptions = fields.filter((f) => f && f.name && SPECIAL_FIELDS.includes(f.name));
    let optionsMap = {};
    if (needOptions.length && terminalId) {
      const names = needOptions.map((f) => f.name);
      optionsMap = await loadOptionsFromDB(terminalId, names);
    }

    fields.forEach((f) => {
      if (!f || !f.name) return;
      // Force special fields to be select with DB-backed options
      if (SPECIAL_FIELDS.includes(f.name)) {
        f.type = 'select';
        const arr = optionsMap[f.name] || [];
        f.options = arr.length ? arr : (f.options || []);
      }
      formArea.appendChild(createFieldEl(f));
    });

    // Dependent dropdowns: Lokasi -> Area -> Item_Cek_ID
    const lokasiEl = formArea.querySelector('#field_Lokasi');
    const lokasiIdEl = formArea.querySelector('#field_ID_Lokasi');
    const areaEl = formArea.querySelector('#field_Area');
    const itemEl = formArea.querySelector('#field_Item_Cek_ID');

    // Cache master lokasi list for mapping name -> id
    let lokasiList = [];
    async function ensureLokasiList() {
      if (lokasiList.length) return;
      try { lokasiList = await fetchJSON('/api/lokasi'); } catch (e) { lokasiList = []; }
    }

    async function onLokasiChange() {
      if (!lokasiEl) return;
      await ensureLokasiList();
      const selectedName = lokasiEl.value;
      const match = lokasiList.find((x) => x.nama_lokasi === selectedName);
      const lid = match ? match.id_lokasi : null;
      // Convert ID_Lokasi select to read-only id text field safely
      const idEl = formArea.querySelector('#field_ID_Lokasi');
      if (idEl && idEl.parentElement) {
        const parent = idEl.parentElement;
        const val = lid != null ? String(lid) : '';
        const text = document.createElement('input');
        text.type = 'text';
        text.id = 'field_ID_Lokasi';
        text.name = 'ID_Lokasi';
        text.value = val;
        text.readOnly = true;
        parent.replaceChild(text, idEl);
      }
      // Load areas for lokasi into Area field if present
      if (areaEl && lid != null) {
        try {
          const areas = await fetchJSON(`/api/lokasi/${encodeURIComponent(lid)}/areas`);
          areaEl.innerHTML = '';
          areas.forEach((a) => {
            const o = document.createElement('option');
            o.value = a.nama_area; // keep text for human-readable, or set to id if schema expects id
            o.textContent = a.nama_area;
            areaEl.appendChild(o);
          });
          // Trigger item reload
          await onAreaChange(lid);
          await renderItemsChecklist(lid);
        } catch (e) {
          // ignore
        }
      } else if (itemEl && lid != null) {
        // If no Area field, list items by lokasi
        try {
          const items = await fetchJSON(`/api/lokasi/${encodeURIComponent(lid)}/items`);
          itemEl.innerHTML = '';
          items.forEach((it) => {
            const o = document.createElement('option');
            o.value = String(it.id_item); // expected to be numeric id
            o.textContent = it.nama_item;
            itemEl.appendChild(o);
          });
        } catch (e) {}
      }
    }

    async function onAreaChange(lid) {
      if (!itemEl || !areaEl) return;
      try {
        // If we had area ids, we'd use that. Given we used nama_area, fetch all and pick selected.
        const areas = await fetchJSON(`/api/lokasi/${encodeURIComponent(lid)}/areas`);
        const selectedName = areaEl.value;
        const am = areas.find((a) => a.nama_area === selectedName);
        if (!am) return;
        const items = await fetchJSON(`/api/area/${encodeURIComponent(am.id_area)}/items`);
        itemEl.innerHTML = '';
        items.forEach((it) => {
          const o = document.createElement('option');
          o.value = String(it.id_item);
          o.textContent = it.nama_item;
          itemEl.appendChild(o);
        });
      } catch (e) { /* ignore */ }
    }

    if (lokasiEl) {
      lokasiEl.addEventListener('change', onLokasiChange);
      onLokasiChange();
    }
    if (areaEl && lokasiEl) {
      areaEl.addEventListener('change', async () => {
        const selectedName = lokasiEl.value;
        const lid = (lokasiList.find((x) => x.nama_lokasi === selectedName) || {}).id_lokasi;
        if (lid != null) {
          await onAreaChange(lid);
          await renderItemsChecklist(lid);
        }
      });
    }
  }

  // Add status controls below Item field
  function ensureStatusControls() {
    const itemWrap = formArea.querySelector('#field_Item_Cek_ID')?.parentElement;
    if (!itemWrap) return;
    if (formArea.querySelector('#status_group')) return;
    const wrap = document.createElement('div');
    wrap.className = 'row';
    wrap.id = 'status_group';
    const label = document.createElement('label');
    label.textContent = 'Status';
    const group = document.createElement('div');
    const good = document.createElement('input'); good.type='radio'; good.name='status_insp'; good.value='Bagus'; good.id='status_bagus'; good.checked=true;
    const rg = document.createElement('label'); rg.htmlFor='status_bagus'; rg.textContent='Bagus'; rg.style.marginRight='12px';
    const bad = document.createElement('input'); bad.type='radio'; bad.name='status_insp'; bad.value='Rusak'; bad.id='status_rusak';
    const rb = document.createElement('label'); rb.htmlFor='status_rusak'; rb.textContent='Rusak';
    const noteWrap = document.createElement('div'); noteWrap.style.marginTop='8px';
    const noteLabel = document.createElement('label'); noteLabel.textContent='Keterangan Kerusakan'; noteLabel.style.display='none'; noteLabel.htmlFor='ket_rusak';
    const note = document.createElement('textarea'); note.id='ket_rusak'; note.rows=3; note.placeholder='Jelaskan kerusakan'; note.style.display='none';
    function sync(){ const isBad = bad.checked; noteLabel.style.display = isBad ? 'block':'none'; note.style.display = isBad ? 'block':'none'; }
    good.addEventListener('change', sync); bad.addEventListener('change', sync);
    group.appendChild(good); group.appendChild(rg); group.appendChild(bad); group.appendChild(rb);
    noteWrap.appendChild(noteLabel); noteWrap.appendChild(note);
    wrap.appendChild(label); wrap.appendChild(group); wrap.appendChild(noteWrap);
    itemWrap.after(wrap);
  }

  async function onTerminalChange() {
    const id = selTerminal.value;
    clearFormArea();
    if (!id) return;
    try {
      const detail = await fetchJSON(`/api/terminals/${encodeURIComponent(id)}`);
      await renderFormSchema(detail && (detail.form_schema || detail.schema));
      // Ensure status controls appear for single-item mode
      ensureStatusControls();
    } catch (err) {
      try { notify('Gagal memuat skema form', 'error'); } catch(_) {}
      const p = document.createElement('p');
      p.className = 'note';
      p.textContent = 'Gagal memuat skema form.';
      formArea.appendChild(p);
    }
  }

  async function captureGeo() {
    if (!navigator.geolocation) {
      setGeoNote('Geolokasi tidak didukung peramban ini.');
      return;
    }
    setGeoNote('Mengambil lokasi...');
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords;
        latEl.value = String(latitude);
        lonEl.value = String(longitude);
        setGeoNote(`Lokasi: ${latitude.toFixed(6)}, ${longitude.toFixed(6)}`, true);
        try {
          const lokasiName = (document.getElementById('field_Lokasi')?.value || '').trim();
          let lokasiList = [];
          try { lokasiList = await fetchJSON('/api/lokasi'); } catch(e) {}
          const found = lokasiList.find(x => x.nama_lokasi === lokasiName);
          const body = { lat: latitude, lon: longitude };
          if (found) body.lokasi_id = found.id_lokasi; else if (lokasiName) body.lokasi_name = lokasiName;
          const verify = await fetchJSON('/api/verify-location', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
          if (verify && verify.valid) {
            setGeoNote('Lokasi terverifikasi ✔️', true);
          } else {
            setGeoNote('Di luar jangkauan lokasi (geofence).');
          }
        } catch (e) {
          try { notify('Gagal verifikasi lokasi', 'warn'); } catch(_) {}
        }
      },
      (err) => {
        setGeoNote(`Gagal mengambil lokasi: ${err.message || err}`);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  }

  function collectFormData() {
    const data = {};
    const list = formArea.querySelectorAll('[data-field-name]');
    list.forEach((el) => {
      const name = el.dataset.fieldName;
      if (!name) return;
      if (el.type === 'checkbox') {
        data[name] = !!el.checked;
      } else {
        data[name] = el.value;
      }
    });
    return data;
  }

  async function submitInspection(e) {
    e.preventDefault();
    setStatus('Mengirim data inspeksi...');

    const terminalId = selTerminal.value;
    if (!terminalId) {
      setStatus('Pilih terminal terlebih dahulu.');
      return;
    }
    // Validate status & note when Rusak
    let statusVal = 'Bagus';
    const rbBad = document.getElementById('status_rusak');
    const note = document.getElementById('ket_rusak');
    if (rbBad && rbBad.checked) {
      statusVal = 'Rusak';
      if (!note || !note.value.trim()) {
        setStatus('Isi keterangan kerusakan.', false);
        return;
      }
    }

    // Verify geofence before submit
    try {
      const lat = Number(latEl.value), lon = Number(lonEl.value);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        setStatus('Ambil lokasi terlebih dahulu.', false); return;
      }
      const lokasiName = (document.getElementById('field_Lokasi')?.value || '').trim();
      let lokasiList = [];
      try { lokasiList = await fetchJSON('/api/lokasi'); } catch(e) {}
      const found = lokasiList.find(x => x.nama_lokasi === lokasiName);
      const body = { lat, lon };
      if (found) body.lokasi_id = found.id_lokasi; else if (lokasiName) body.lokasi_name = lokasiName;
      const verify = await fetchJSON('/api/verify-location', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      if (!(verify && verify.valid)) { setStatus('Di luar jangkauan lokasi (geofence).', false); return; }
    } catch (e) { setStatus('Gagal verifikasi lokasi.', false); return; }

    const payload = {
      terminal_id: Number(terminalId),
      lat: latEl.value ? Number(latEl.value) : null,
      lon: lonEl.value ? Number(lonEl.value) : null,
      data: { ...collectFormData(), status: statusVal, keterangan: (document.getElementById('ket_rusak')?.value || '').trim() },
    };

    // Try a conventional endpoint; if missing, degrade gracefully
    try {
      const res = await fetch('/api/inspections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setStatus('Inspeksi berhasil dikirim.', true);
        form.reset();
        clearFormArea();
        return;
      }
      // If not OK, try alternative path
      const alt = await fetch('/api/inspections/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (alt.ok) {
        setStatus('Inspeksi berhasil dikirim.', true);
        form.reset();
        clearFormArea();
        return;
      }
      // Both failed -> show message
      setStatus('Endpoint pengiriman belum tersedia di server.');
      try { notify('Endpoint pengiriman belum tersedia', 'warn'); } catch(_) {}
    } catch (err) {
      setStatus(`Gagal mengirim: ${err.message || err}`);
      try { notify('Gagal mengirim inspeksi', 'error'); } catch(_) {}
    }
  }

  // Init
  loadTerminals();
  selTerminal.addEventListener('change', onTerminalChange);
  btnGeo.addEventListener('click', captureGeo);
  form.addEventListener('submit', submitInspection);
  // Slight delay to allow fields render then attach status controls
  setTimeout(ensureStatusControls, 300);
})();
