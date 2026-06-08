import React, { useState, useEffect, createContext, useContext } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate, useLocation } from 'react-router-dom';
import './styles/App.css';

const API = '';

async function api(path, options = {}) {
  const token = localStorage.getItem('token');
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (res.status === 401) { localStorage.removeItem('token'); localStorage.removeItem('user'); window.location.href = '/login'; return null; }
  return res.json();
}

const AuthContext = createContext(null);

function AuthProvider({ children }) {
  const [user, setUser] = useState(() => { const s = localStorage.getItem('user'); return s ? JSON.parse(s) : null; });
  const login = async (username, password) => {
    const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    if (data?.access_token) { localStorage.setItem('token', data.access_token); localStorage.setItem('user', JSON.stringify(data.user)); setUser(data.user); return true; }
    return false;
  };
  const logout = () => { api('/api/auth/logout', { method: 'POST' }); localStorage.removeItem('token'); localStorage.removeItem('user'); setUser(null); };
  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}
function useAuth() { return useContext(AuthContext); }

// === LOGIN ===
function LoginPage() {
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const { login } = useAuth(); const navigate = useNavigate();
  const handleSubmit = async (e) => { e.preventDefault(); setLoading(true); setError(''); const ok = await login(username, password); setLoading(false); if (ok) navigate('/'); else setError('Credenciales incorrectas'); };
  return (
    <div className="login-page"><div className="login-card"><div className="login-logo"><div className="login-icon">G</div><h1>GECA Brands</h1><p>Gestión de marcas para detección en video</p></div>
      <form onSubmit={handleSubmit}>
        {error && <div className="error-msg">{error}</div>}
        <div className="form-group"><label>Usuario</label><input type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" required /></div>
        <div className="form-group"><label>Contraseña</label><input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••" required /></div>
        <button type="submit" className="btn-primary btn-full" disabled={loading}>{loading ? 'Entrando...' : 'Iniciar Sesión'}</button>
      </form>
      <div className="login-footer"><span>Admin por defecto: admin / admin123</span></div>
    </div></div>
  );
}

// === LAYOUT ===
function Layout({ children }) {
  const { user, logout } = useAuth(); const location = useLocation();
  const navItems = [{ path: '/', label: 'Dashboard', icon: '◆' }, { path: '/brands', label: 'Marcas', icon: '◎' }, { path: '/contexts', label: 'Contextos', icon: '▦' }, { path: '/videos', label: 'Videos', icon: '▶' }, { path: '/cvat', label: 'CVAT', icon: '⬡' }];
  if (user?.role === 'admin') navItems.push({ path: '/users', label: 'Usuarios', icon: '◇' });
  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-brand"><div className="brand-icon">G</div><span className="brand-text">GECA</span></div>
        <div className="sidebar-nav">{navItems.map(item => (<Link key={item.path} to={item.path} className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}><span className="nav-icon">{item.icon}</span><span className="nav-label">{item.label}</span></Link>))}</div>
        <div className="sidebar-footer"><div className="user-info"><div className="user-avatar">{user?.username?.[0]?.toUpperCase()}</div><div className="user-details"><span className="user-name">{user?.username}</span><span className="user-role">{user?.role}</span></div></div><button className="btn-logout" onClick={logout}>Salir</button></div>
      </nav>
      <main className="main-content">{children}</main>
    </div>
  );
}

// === DASHBOARD ===
function DashboardPage() {
  const [stats, setStats] = useState(null);
  useEffect(() => { api('/api/stats').then(setStats); }, []);
  if (!stats) return <div className="page"><div className="loading">Cargando...</div></div>;
  const cards = [{ label: 'Marcas', value: stats.total_brands, icon: '◎', color: '#6c5ce7' }, { label: 'Submarcas', value: stats.total_subbrands, icon: '◈', color: '#00b894' }, { label: 'Contextos', value: stats.total_contexts, icon: '▦', color: '#e17055' }, { label: 'Usuarios', value: stats.total_users, icon: '◇', color: '#0984e3' }];
  return (
    <div className="page"><div className="page-header"><h1>Dashboard</h1><p>Resumen del sistema de gestión de marcas</p></div>
      <div className="stats-grid">{cards.map(c => (<div className="stat-card" key={c.label} style={{ '--accent': c.color }}><div className="stat-icon">{c.icon}</div><div className="stat-value">{c.value}</div><div className="stat-label">{c.label}</div></div>))}</div>
    </div>
  );
}

// === BRANDS ===
function BrandsPage() {
  const [brands, setBrands] = useState([]); const [contexts, setContexts] = useState([]);
  const [showForm, setShowForm] = useState(false); const [showSubForm, setShowSubForm] = useState(null); const [expanded, setExpanded] = useState(null);
  const [form, setForm] = useState({ name: '', display_name: '', color: '#6c5ce7', client: '' });
  const [subForm, setSubForm] = useState({ context_id: '', cvat_label: '', description: '', min_training_images: 200 });
  const [aliasEdits, setAliasEdits] = useState({});
  const load = () => { api('/api/brands').then(setBrands); api('/api/contexts').then(setContexts); };
  useEffect(load, []);
  const createBrand = async (e) => { e.preventDefault(); await api('/api/brands', { method: 'POST', body: JSON.stringify(form) }); setForm({ name: '', display_name: '', color: '#6c5ce7', client: '' }); setShowForm(false); load(); };
  const deleteBrand = async (id) => { if (window.confirm('¿Eliminar esta marca y todas sus submarcas?')) { await api(`/api/brands/${id}`, { method: 'DELETE' }); load(); } };
  const createSubBrand = async (e, brandId) => { e.preventDefault(); await api('/api/subbrands', { method: 'POST', body: JSON.stringify({ ...subForm, brand_id: brandId, context_id: parseInt(subForm.context_id) }) }); setSubForm({ context_id: '', cvat_label: '', description: '', min_training_images: 200 }); setShowSubForm(null); load(); };
  const deleteSubBrand = async (id) => { if (window.confirm('¿Eliminar esta submarca?')) { await api(`/api/subbrands/${id}`, { method: 'DELETE' }); load(); } };
  const saveAliases = async (brandId) => {
    await api(`/api/brands/${brandId}`, { method: 'PUT', body: JSON.stringify({ audio_aliases: aliasEdits[brandId] }) });
    load();
  };
  const initAlias = (brand) => { if (!(brand.id in aliasEdits)) setAliasEdits(prev => ({...prev, [brand.id]: brand.audio_aliases || ''})); };
  return (
    <div className="page">
      <div className="page-header"><div><h1>Marcas</h1><p>Gestiona marcas y sus variantes por contexto</p></div><button className="btn-primary" onClick={() => setShowForm(!showForm)}>+ Nueva Marca</button></div>
      {showForm && (<div className="card form-card"><h3>Nueva Marca</h3><form onSubmit={createBrand}><div className="form-row"><div className="form-group"><label>Nombre (ID)</label><input placeholder="cocacola" value={form.name} onChange={e => setForm({...form, name: e.target.value})} required /></div><div className="form-group"><label>Nombre Display</label><input placeholder="Coca-Cola" value={form.display_name} onChange={e => setForm({...form, display_name: e.target.value})} required /></div><div className="form-group"><label>Cliente</label><input placeholder="The Coca-Cola Company" value={form.client} onChange={e => setForm({...form, client: e.target.value})} /></div><div className="form-group" style={{maxWidth: 100}}><label>Color</label><input type="color" value={form.color} onChange={e => setForm({...form, color: e.target.value})} /></div></div><div className="form-actions"><button type="submit" className="btn-primary">Crear</button><button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancelar</button></div></form></div>)}
      <div className="brands-list">{brands.map(brand => (<div className="card brand-card" key={brand.id}><div className="brand-header" onClick={() => { setExpanded(expanded === brand.id ? null : brand.id); initAlias(brand); }}><div className="brand-color" style={{ background: brand.color }}></div><div className="brand-info"><h3>{brand.display_name}</h3><span className="brand-meta">{brand.name} · {brand.client || 'Sin cliente'}</span></div><div className="brand-badges"><span className="badge">{brand.subbrands?.length || 0} submarcas</span></div><span className={`expand-icon ${expanded === brand.id ? 'open' : ''}`}>▸</span></div>
        {expanded === brand.id && (<div className="brand-body">
          <div className="aliases-section">
            <div className="form-group">
              <label>Aliases de audio (variantes fonéticas separadas por coma)</label>
              <input placeholder="naiki, naik, naikee" value={aliasEdits[brand.id] ?? brand.audio_aliases ?? ''} onChange={e => setAliasEdits(prev => ({...prev, [brand.id]: e.target.value}))} />
            </div>
            <button className="btn-sm btn-primary" style={{marginTop: 6}} onClick={() => saveAliases(brand.id)}>Guardar aliases</button>
          </div>
          <div className="subbrands-list">{brand.subbrands?.map(sb => (<div className="subbrand-item" key={sb.id}><span className="subbrand-context">{sb.context_icon} {sb.context}</span><code className="subbrand-label">{sb.cvat_label}</code><span className={`status ${sb.is_active ? 'active' : 'inactive'}`}>{sb.is_active ? 'Activo' : 'Inactivo'}</span><button className="btn-icon btn-danger-icon" onClick={() => deleteSubBrand(sb.id)}>✕</button></div>))}{(!brand.subbrands || brand.subbrands.length === 0) && <p className="empty-text">No hay submarcas. Agrega una para empezar a anotar.</p>}</div>
          {showSubForm === brand.id ? (<form className="subbrand-form" onSubmit={(e) => createSubBrand(e, brand.id)}><div className="form-row"><div className="form-group"><label>Contexto</label><select value={subForm.context_id} onChange={e => setSubForm({...subForm, context_id: e.target.value})} required><option value="">Seleccionar...</option>{contexts.map(c => (<option key={c.id} value={c.id}>{c.icon} {c.name}</option>))}</select></div><div className="form-group"><label>Label CVAT</label><input placeholder={`${brand.name}_camiseta`} value={subForm.cvat_label} onChange={e => setSubForm({...subForm, cvat_label: e.target.value})} required /></div><div className="form-group"><label>Mín. imágenes</label><input type="number" value={subForm.min_training_images} onChange={e => setSubForm({...subForm, min_training_images: parseInt(e.target.value)})} /></div></div><div className="form-actions"><button type="submit" className="btn-primary btn-sm">Agregar</button><button type="button" className="btn-secondary btn-sm" onClick={() => setShowSubForm(null)}>Cancelar</button></div></form>
          ) : (<div className="brand-actions"><button className="btn-secondary btn-sm" onClick={() => setShowSubForm(brand.id)}>+ Submarca</button><button className="btn-danger btn-sm" onClick={() => deleteBrand(brand.id)}>Eliminar marca</button></div>)}
        </div>)}</div>))}
        {brands.length === 0 && <div className="empty-state"><div className="empty-icon">◎</div><p>No hay marcas registradas</p><button className="btn-primary" onClick={() => setShowForm(true)}>Crear primera marca</button></div>}
      </div>
    </div>
  );
}

// === CONTEXTS ===
function ContextsPage() {
  const [contexts, setContexts] = useState([]); const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', icon: '' });
  const load = () => api('/api/contexts').then(setContexts);
  useEffect(load, []);
  const create = async (e) => { e.preventDefault(); await api('/api/contexts', { method: 'POST', body: JSON.stringify(form) }); setForm({ name: '', description: '', icon: '' }); setShowForm(false); load(); };
  const remove = async (id) => { if (window.confirm('¿Eliminar este contexto?')) { await api(`/api/contexts/${id}`, { method: 'DELETE' }); load(); } };
  return (
    <div className="page"><div className="page-header"><div><h1>Contextos</h1><p>Superficies donde aparecen las marcas</p></div><button className="btn-primary" onClick={() => setShowForm(!showForm)}>+ Nuevo Contexto</button></div>
      {showForm && (<div className="card form-card"><h3>Nuevo Contexto</h3><form onSubmit={create}><div className="form-row"><div className="form-group" style={{maxWidth: 80}}><label>Icono</label><input placeholder="👕" value={form.icon} onChange={e => setForm({...form, icon: e.target.value})} /></div><div className="form-group"><label>Nombre</label><input placeholder="camiseta" value={form.name} onChange={e => setForm({...form, name: e.target.value})} required /></div><div className="form-group" style={{flex: 2}}><label>Descripción</label><input placeholder="Logo en camiseta de jugador" value={form.description} onChange={e => setForm({...form, description: e.target.value})} /></div></div><div className="form-actions"><button type="submit" className="btn-primary">Crear</button><button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancelar</button></div></form></div>)}
      <div className="contexts-grid">{contexts.map(ctx => (<div className="card context-card" key={ctx.id}><div className="context-icon">{ctx.icon || '▦'}</div><h3>{ctx.name}</h3><p>{ctx.description || 'Sin descripción'}</p><button className="btn-icon btn-danger-icon" onClick={() => remove(ctx.id)}>✕</button></div>))}</div>
    </div>
  );
}

// === CVAT PAGE (with settings) ===
function CVATPage() {
  const { user } = useAuth();
  const [tasks, setTasks] = useState([]); const [subbrands, setSubbrands] = useState([]);
  const [labelStats, setLabelStats] = useState({}); const [loading, setLoading] = useState(true);
  const [cvatConfig, setCvatConfig] = useState(null); const [showConfig, setShowConfig] = useState(false);
  const [configForm, setConfigForm] = useState({ cvat_url: '', cvat_host: '', cvat_username: '', cvat_password: '' });
  const [testResult, setTestResult] = useState(null); const [saving, setSaving] = useState(false);

  const loadData = () => {
    setLoading(true);
    Promise.all([api('/api/settings/cvat'), api('/api/cvat/tasks'), api('/api/subbrands')]).then(([cfg, tasksData, subs]) => {
      setCvatConfig(cfg);
      setTasks(tasksData?.tasks || []);
      setSubbrands(subs || []);
      if (cfg && !cfg.configured) setShowConfig(true);
      setLoading(false);
    });
  };
  useEffect(loadData, []);

  const saveConfig = async (e) => {
    e.preventDefault(); setSaving(true);
    await api('/api/settings/cvat', { method: 'POST', body: JSON.stringify(configForm) });
    setSaving(false); setShowConfig(false); setTestResult(null); loadData();
  };

  const testConnection = async () => {
    setTestResult({ testing: true });
    const result = await api('/api/settings/cvat/test');
    setTestResult(result);
  };

  const checkLabel = async (label) => {
    setLabelStats(prev => ({ ...prev, [label]: { loading: true } }));
    const stats = await api(`/api/cvat/labels/${label}`);
    setLabelStats(prev => ({ ...prev, [label]: stats }));
  };

  const openConfig = () => {
    setConfigForm({
      cvat_url: cvatConfig?.cvat_url || 'http://cvat_server:8080',
      cvat_host: cvatConfig?.cvat_host || '',
      cvat_username: cvatConfig?.cvat_username || '',
      cvat_password: '',
    });
    setShowConfig(true); setTestResult(null);
  };

  if (loading) return <div className="page"><div className="loading">Cargando...</div></div>;

  return (
    <div className="page">
      <div className="page-header">
        <div><h1>Integración CVAT</h1><p>Estado de los datasets de entrenamiento</p></div>
        <div style={{display:'flex', gap: 8}}>
          {user?.role === 'admin' && <button className="btn-secondary" onClick={openConfig}>⚙ Configurar</button>}
          {cvatConfig?.configured && <a href={`http://${cvatConfig.cvat_host || window.location.hostname}:8080`} target="_blank" rel="noreferrer" className="btn-primary">Abrir CVAT ↗</a>}
        </div>
      </div>

      {/* CONFIG FORM */}
      {showConfig && (
        <div className="card form-card">
          <h3>Configuración de CVAT</h3>
          <p className="section-desc">Configura la conexión con tu instancia de CVAT</p>
          <form onSubmit={saveConfig}>
            <div className="form-row">
              <div className="form-group"><label>URL interna</label><input placeholder="http://cvat_server:8080" value={configForm.cvat_url} onChange={e => setConfigForm({...configForm, cvat_url: e.target.value})} required /></div>
              <div className="form-group"><label>Host (IP externa)</label><input placeholder="10.43.13.204" value={configForm.cvat_host} onChange={e => setConfigForm({...configForm, cvat_host: e.target.value})} required /></div>
            </div>
            <div className="form-row">
              <div className="form-group"><label>Usuario CVAT</label><input placeholder="admin" value={configForm.cvat_username} onChange={e => setConfigForm({...configForm, cvat_username: e.target.value})} required /></div>
              <div className="form-group"><label>Contraseña CVAT</label><input type="password" placeholder={cvatConfig?.has_password ? '••••••  (ya configurada)' : 'Contraseña'} value={configForm.cvat_password} onChange={e => setConfigForm({...configForm, cvat_password: e.target.value})} required={!cvatConfig?.has_password} /></div>
            </div>
            {testResult && !testResult.testing && (
              <div className={`test-result ${testResult.connected ? 'success' : 'error'}`}>
                {testResult.connected ? '✓ ' + testResult.message : '✕ ' + testResult.error}
              </div>
            )}
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={testConnection}>{testResult?.testing ? 'Probando...' : 'Probar conexión'}</button>
              <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Guardando...' : 'Guardar'}</button>
              <button type="button" className="btn-secondary" onClick={() => setShowConfig(false)}>Cancelar</button>
            </div>
          </form>
        </div>
      )}

      {!cvatConfig?.configured && !showConfig && (
        <div className="empty-state"><div className="empty-icon">⬡</div><p>CVAT no está configurado</p><button className="btn-primary" onClick={openConfig}>Configurar conexión</button></div>
      )}

      {cvatConfig?.configured && (
        <>
          <div className="section">
            <h2>Progreso por Submarca</h2><p className="section-desc">Consulta cuántas imágenes anotadas hay para cada label</p>
            <div className="label-check-grid">
              {subbrands.map(sb => { const stats = labelStats[sb.cvat_label]; return (
                <div className="card label-card" key={sb.id}><div className="label-header"><code>{sb.cvat_label}</code><button className="btn-sm btn-secondary" onClick={() => checkLabel(sb.cvat_label)}>{stats?.loading ? '...' : 'Consultar'}</button></div>
                  {stats && !stats.loading && (<div className="label-stats"><div className="progress-bar"><div className="progress-fill" style={{ width: `${stats.progress_pct || 0}%` }}></div></div><div className="progress-info"><span>{stats.total_images || 0} / {stats.min_required || 200} imágenes</span><span className={stats.ready_to_train ? 'text-green' : 'text-orange'}>{stats.ready_to_train ? '✓ Listo para entrenar' : 'Faltan imágenes'}</span></div></div>)}
                </div>); })}
              {subbrands.length === 0 && <div className="empty-text">Crea marcas y submarcas primero para ver el progreso</div>}
            </div>
          </div>
          <div className="section">
            <h2>Tareas CVAT</h2>
            <div className="tasks-list">{tasks.map(t => (<div className="card task-card" key={t.id}><div className="task-info"><h4>{t.name}</h4><span className="task-meta">{t.size} frames · {t.labels?.join(', ') || 'sin labels'}</span></div><span className={`status ${t.status}`}>{t.status}</span></div>))}{tasks.length === 0 && <div className="empty-text">No hay tareas en CVAT</div>}</div>
          </div>
        </>
      )}
    </div>
  );
}

// === USERS ===
function UsersPage() {
  const [users, setUsers] = useState([]); const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'annotator' });
  const load = () => api('/api/users').then(data => { if (data) setUsers(data); });
  useEffect(load, []);
  const create = async (e) => { e.preventDefault(); await api('/api/users', { method: 'POST', body: JSON.stringify(form) }); setForm({ username: '', email: '', password: '', role: 'annotator' }); setShowForm(false); load(); };
  return (
    <div className="page"><div className="page-header"><div><h1>Usuarios</h1><p>Gestión de accesos al sistema</p></div><button className="btn-primary" onClick={() => setShowForm(!showForm)}>+ Nuevo Usuario</button></div>
      {showForm && (<div className="card form-card"><h3>Nuevo Usuario</h3><form onSubmit={create}><div className="form-row"><div className="form-group"><label>Usuario</label><input value={form.username} onChange={e => setForm({...form, username: e.target.value})} required /></div><div className="form-group"><label>Email</label><input type="email" value={form.email} onChange={e => setForm({...form, email: e.target.value})} required /></div><div className="form-group"><label>Contraseña</label><input type="password" value={form.password} onChange={e => setForm({...form, password: e.target.value})} required /></div><div className="form-group"><label>Rol</label><select value={form.role} onChange={e => setForm({...form, role: e.target.value})}><option value="admin">Admin</option><option value="annotator">Anotador</option><option value="viewer">Viewer</option></select></div></div><div className="form-actions"><button type="submit" className="btn-primary">Crear</button><button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancelar</button></div></form></div>)}
      <div className="users-list">{users.map(u => (<div className="card user-card" key={u.id}><div className="user-card-avatar">{u.username[0].toUpperCase()}</div><div className="user-card-info"><h4>{u.username}</h4><span>{u.email}</span></div><span className={`badge role-${u.role}`}>{u.role}</span></div>))}</div>
    </div>
  );
}

// === VIDEOS ===
function VideosPage() {
  const [videos, setVideos] = useState([]); const [loading, setLoading] = useState(true);
  const [totalSize, setTotalSize] = useState('');
  const [extracting, setExtracting] = useState(null); const [interval, setInterval_] = useState(10);
  const [extractStatus, setExtractStatus] = useState(null);
  const [viewingFrames, setViewingFrames] = useState(null);
  const [frames, setFrames] = useState([]); const [framesPage, setFramesPage] = useState(1);
  const [framesTotalPages, setFramesTotalPages] = useState(0); const [framesTotal, setFramesTotal] = useState(0);
  // Audio state
  const [audioProcessing, setAudioProcessing] = useState(null);
  const [audioStatus, setAudioStatus] = useState(null);
  const [viewingMentions, setViewingMentions] = useState(null);
  const [mentions, setMentions] = useState(null);

  const load = () => {
    setLoading(true);
    api('/api/videos').then(data => {
      if (data) {
        setVideos(data.videos || []);
        const total = (data.videos || []).reduce((s, v) => s + v.size_bytes, 0);
        if (total >= 1e9) setTotalSize(`${(total / 1e9).toFixed(1)} GB`);
        else setTotalSize(`${(total / 1e6).toFixed(1)} MB`);
      }
      setLoading(false);
    });
  };
  useEffect(load, []);

  const estimateFrames = (v) => {
    if (!v.duration_secs || v.duration_secs <= 0) return '?';
    return Math.floor(v.duration_secs / interval) + 1;
  };

  const startExtraction = async (v) => {
    setExtractStatus({ status: 'starting' });
    const res = await api(`/api/videos/${encodeURIComponent(v.name)}/extract`, {
      method: 'POST', body: JSON.stringify({ interval: interval })
    });
    if (res?.status === 'started' || res?.status === 'already_running') pollStatus(v.name);
  };

  const pollStatus = (filename) => {
    const poll = setIntervalFn(() => {
      api(`/api/videos/${encodeURIComponent(filename)}/extract/status`).then(s => {
        setExtractStatus(s);
        if (s?.status === 'done' || s?.status === 'error') { clearInterval(poll); load(); }
      });
    }, 2000);
  };

  const setIntervalFn = (fn, ms) => { fn(); return window.setInterval(fn, ms); };

  const loadFrames = (folder, page = 1) => {
    setViewingFrames(folder); setFramesPage(page);
    api(`/api/frames/${encodeURIComponent(folder)}?page=${page}&per_page=24`).then(data => {
      if (data) { setFrames(data.frames || []); setFramesTotalPages(data.total_pages); setFramesTotal(data.total); }
    });
  };

  // Audio functions
  const startAudio = async (v) => {
    setAudioProcessing(v.name);
    setAudioStatus({ status: 'starting', phase: 'starting', progress: 0, message: 'Iniciando...' });
    await api(`/api/videos/${encodeURIComponent(v.name)}/process-audio`, { method: 'POST' });
    pollAudioStatus(v.name);
  };

  const pollAudioStatus = (filename) => {
    const stem = filename.replace(/\.[^.]+$/, '');
    const poll = setIntervalFn(() => {
      api(`/api/videos/${encodeURIComponent(filename)}/audio/status`).then(s => {
        setAudioStatus(s);
        if (s?.status === 'done' || s?.status === 'error') { clearInterval(poll); load(); }
      });
    }, 3000);
  };

  const loadMentions = async (filename) => {
    const data = await api(`/api/videos/${encodeURIComponent(filename)}/mentions`);
    setMentions(data);
    setViewingMentions(filename);
  };

  if (loading) return <div className="page"><div className="loading">Escaneando carpeta de videos...</div></div>;

  // MENTIONS VIEW
  if (viewingMentions && mentions) {
    const brands = mentions.brands || {};
    const brandList = Object.entries(brands).sort((a, b) => b[1].count - a[1].count);
    return (
      <div className="page">
        <div className="page-header">
          <div><h1>Menciones: {viewingMentions.replace(/\.[^.]+$/, '')}</h1><p>{mentions.total_mentions || 0} menciones encontradas</p></div>
          <button className="btn-secondary" onClick={() => { setViewingMentions(null); setMentions(null); }}>← Volver a Videos</button>
        </div>
        {brandList.length === 0 && <div className="empty-state"><div className="empty-icon">🎙</div><p>No se encontraron menciones de marcas en el audio</p></div>}
        {brandList.map(([brandName, info]) => (
          <div className="card mention-brand-card" key={brandName}>
            <div className="mention-brand-header">
              <div className="mention-brand-color" style={{background: info.color || '#6c5ce7'}}></div>
              <h3>{brandName}</h3>
              <span className="badge">{info.count} menciones</span>
            </div>
            <div className="mention-list">
              {info.mentions?.map((m, i) => (
                <div className="mention-item" key={i}>
                  <span className="mention-time">{m.start_fmt}</span>
                  <span className="mention-text">"{m.text}"</span>
                  <span className="mention-term">↳ {m.matched_term}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // FRAME GALLERY VIEW
  if (viewingFrames) {
    return (
      <div className="page">
        <div className="page-header">
          <div><h1>Frames: {viewingFrames}</h1><p>{framesTotal} imágenes extraídas</p></div>
          <button className="btn-secondary" onClick={() => { setViewingFrames(null); setFrames([]); }}>← Volver a Videos</button>
        </div>
        <div className="frames-grid">
          {frames.map(f => (<div className="frame-card" key={f.name}><img src={f.url} alt={f.name} loading="lazy" /><span className="frame-name">{f.name}</span></div>))}
        </div>
        {framesTotalPages > 1 && (
          <div className="frames-pagination">
            <button className="btn-sm btn-secondary" disabled={framesPage <= 1} onClick={() => loadFrames(viewingFrames, framesPage - 1)}>← Anterior</button>
            <span className="pagination-info">Página {framesPage} de {framesTotalPages}</span>
            <button className="btn-sm btn-secondary" disabled={framesPage >= framesTotalPages} onClick={() => loadFrames(viewingFrames, framesPage + 1)}>Siguiente →</button>
          </div>
        )}
      </div>
    );
  }

  // VIDEOS LIST VIEW
  return (
    <div className="page">
      <div className="page-header">
        <div><h1>Videos</h1><p>Videos disponibles en la carpeta compartida</p></div>
        <button className="btn-secondary" onClick={load}>↻ Actualizar</button>
      </div>

      <div className="video-summary">
        <div className="video-summary-item"><span className="video-summary-value">{videos.length}</span><span className="video-summary-label">Videos</span></div>
        <div className="video-summary-item"><span className="video-summary-value">{totalSize}</span><span className="video-summary-label">Total</span></div>
      </div>

      <div className="video-instructions">
        <p>Para agregar videos, copia archivos desde Windows a:</p>
        <code>\\esgecafs001.imagina.local\Aplicaciones\IAjesus\videos\</code>
      </div>

      <div className="videos-list">
        {videos.map(v => (
          <div className="card video-card-full" key={v.name}>
            <div className="video-card-top">
              <div className="video-icon">▶</div>
              <div className="video-info">
                <h4>{v.name}</h4>
                <div className="video-meta">
                  <span>{v.size}</span><span>·</span><span>{v.duration}</span><span>·</span><span>{v.extension.toUpperCase()}</span>
                </div>
              </div>
              <div className="video-top-buttons">
                {v.frames_count > 0 && <button className="btn-sm btn-primary" onClick={() => loadFrames(v.frames_folder)}>📷 {v.frames_count} frames</button>}
              </div>
            </div>

            {/* Audio processing status */}
            {audioProcessing === v.name && audioStatus?.status === 'running' && (
              <div className="extract-panel">
                <div className="extract-progress">
                  <div className="audio-phase">{audioStatus.phase === 'audio' ? '🔊' : audioStatus.phase === 'transcribe' ? '🎙' : '🔍'} {audioStatus.message}</div>
                  <div className="progress-bar"><div className="progress-fill" style={{ width: `${audioStatus.progress || 0}%` }}></div></div>
                  <div className="progress-info"><span>{audioStatus.phase}</span><span>{audioStatus.progress || 0}%</span></div>
                </div>
              </div>
            )}
            {audioProcessing === v.name && audioStatus?.status === 'done' && (
              <div className="extract-panel">
                <div className="test-result success">
                  ✓ Audio procesado: {audioStatus.total_mentions || 0} menciones en {audioStatus.segments || 0} segmentos
                  <button className="btn-sm btn-primary" style={{marginLeft: 12}} onClick={() => { setAudioProcessing(null); loadMentions(v.name); }}>Ver menciones</button>
                </div>
              </div>
            )}
            {audioProcessing === v.name && audioStatus?.status === 'error' && (
              <div className="extract-panel"><div className="test-result error">✕ Error: {audioStatus.message}</div></div>
            )}

            {/* Extraction UI */}
            {extracting === v.name ? (
              <div className="extract-panel">
                {extractStatus?.status === 'running' ? (
                  <div className="extract-progress">
                    <div className="progress-bar"><div className="progress-fill" style={{ width: `${extractStatus.progress || 0}%` }}></div></div>
                    <div className="progress-info"><span>Extrayendo... {extractStatus.extracted || 0} / {extractStatus.total || '?'} frames</span><span>{extractStatus.progress || 0}%</span></div>
                  </div>
                ) : extractStatus?.status === 'done' ? (
                  <div className="test-result success">
                    ✓ {extractStatus.extracted} frames generados
                    <button className="btn-sm btn-primary" style={{marginLeft: 12}} onClick={() => { setExtracting(null); setExtractStatus(null); loadFrames(v.frames_folder || v.name.replace(/\.[^.]+$/, '')); }}>Ver frames</button>
                  </div>
                ) : extractStatus?.status === 'error' ? (
                  <div className="test-result error">✕ Error: {extractStatus.message}</div>
                ) : (
                  <div className="extract-form">
                    <div className="extract-row">
                      <div className="form-group" style={{maxWidth: 160}}><label>Intervalo (segundos)</label><input type="number" value={interval} min={1} max={300} onChange={e => setInterval_(parseInt(e.target.value) || 10)} /></div>
                      <div className="extract-estimate"><span className="extract-estimate-value">{estimateFrames(v)}</span><span className="extract-estimate-label">imágenes estimadas</span></div>
                    </div>
                    <div className="form-actions">
                      <button className="btn-primary btn-sm" onClick={() => startExtraction(v)}>Extraer frames</button>
                      <button className="btn-secondary btn-sm" onClick={() => { setExtracting(null); setExtractStatus(null); }}>Cancelar</button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="video-card-actions">
                <button className="btn-sm btn-secondary" onClick={() => { setExtracting(v.name); setExtractStatus(null); }}>✂ Extraer frames</button>
                <button className="btn-sm btn-secondary" onClick={() => startAudio(v)}>🎙 Procesar audio</button>
                <button className="btn-sm btn-secondary" onClick={() => loadMentions(v.name)}>📋 Ver menciones</button>
              </div>
            )}
          </div>
        ))}
        {videos.length === 0 && (
          <div className="empty-state"><div className="empty-icon">▶</div><p>No hay videos en la carpeta compartida</p></div>
        )}
      </div>
    </div>
  );
}

function ProtectedRoute({ children }) { const { user } = useAuth(); if (!user) return <Navigate to="/login" />; return <Layout>{children}</Layout>; }

function App() {
  return (
    <BrowserRouter><AuthProvider><Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/brands" element={<ProtectedRoute><BrandsPage /></ProtectedRoute>} />
      <Route path="/contexts" element={<ProtectedRoute><ContextsPage /></ProtectedRoute>} />
      <Route path="/videos" element={<ProtectedRoute><VideosPage /></ProtectedRoute>} />
      <Route path="/cvat" element={<ProtectedRoute><CVATPage /></ProtectedRoute>} />
      <Route path="/users" element={<ProtectedRoute><UsersPage /></ProtectedRoute>} />
    </Routes></AuthProvider></BrowserRouter>
  );
}

export default App;
