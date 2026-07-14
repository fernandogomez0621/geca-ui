import React, { useState, useEffect, createContext, useContext } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate, useLocation } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, Legend, AreaChart, Area } from 'recharts';
import * as XLSX from 'xlsx';
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
  const [selectedFrames, setSelectedFrames] = useState(new Set());
  const [showCvatForm, setShowCvatForm] = useState(false);
  const [cvatTaskName, setCvatTaskName] = useState('');
  const [cvatLabels, setCvatLabels] = useState([]);
  // Audio state
  const [audioProcessing, setAudioProcessing] = useState(null);
  const [audioStatus, setAudioStatus] = useState(null);
  const [viewingMentions, setViewingMentions] = useState(null);
  const [mentions, setMentions] = useState(null);
  // Transcription state
  const [viewingTranscription, setViewingTranscription] = useState(null);
  const [transData, setTransData] = useState(null);
  const [transPage, setTransPage] = useState(1);
  const [transSearch, setTransSearch] = useState('');
  const [transStartTime, setTransStartTime] = useState('');
  const [transEndTime, setTransEndTime] = useState('');
  // Analytics state
  const [viewingAnalytics, setViewingAnalytics] = useState(null);
  const [analytics, setAnalytics] = useState(null);

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
    setViewingFrames(folder); setFramesPage(page); setSelectedFrames(new Set());
    api(`/api/frames/${encodeURIComponent(folder)}?page=${page}&per_page=24`).then(data => {
      if (data) { setFrames(data.frames || []); setFramesTotalPages(data.total_pages); setFramesTotal(data.total); }
    });
  };

  const toggleFrame = (name) => {
    setSelectedFrames(prev => { const s = new Set(prev); s.has(name) ? s.delete(name) : s.add(name); return s; });
  };
  const selectAllFrames = () => { setSelectedFrames(new Set(frames.map(f => f.name))); };
  const deselectAll = () => { setSelectedFrames(new Set()); };

  const deleteSelectedFrames = async () => {
    if (selectedFrames.size === 0) return;
    if (!window.confirm(`¿Eliminar ${selectedFrames.size} frames seleccionados?`)) return;
    await api(`/api/frames/${encodeURIComponent(viewingFrames)}/delete-batch`, {
      method: 'POST', body: JSON.stringify({ frames: [...selectedFrames] })
    });
    setSelectedFrames(new Set());
    loadFrames(viewingFrames, framesPage);
  };

  const deleteSingleFrame = async (folder, name) => {
    await api(`/api/frames/${encodeURIComponent(folder)}/${encodeURIComponent(name)}`, { method: 'DELETE' });
    loadFrames(folder, framesPage);
  };

  const createCvatTask = async () => {
    if (!cvatTaskName) return;
    const res = await api(`/api/frames/${encodeURIComponent(viewingFrames)}/create-cvat-task`, {
      method: 'POST', body: JSON.stringify({ task_name: cvatTaskName, labels: cvatLabels })
    });
    if (res?.status === 'ok') {
      alert(`✓ Tarea "${res.task_name}" creada en CVAT con ${res.frames_uploaded} frames`);
      setShowCvatForm(false); setCvatTaskName('');
    } else {
      alert(`✕ Error: ${res?.message || 'No se pudo crear'}`);
    }
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

  const loadTranscription = async (filename, page = 1) => {
    let url = `/api/videos/${encodeURIComponent(filename)}/transcription?page=${page}&per_page=30`;
    if (transSearch) url += `&search=${encodeURIComponent(transSearch)}`;
    if (transStartTime) url += `&start_time=${parseTimeToSecs(transStartTime)}`;
    if (transEndTime) url += `&end_time=${parseTimeToSecs(transEndTime)}`;
    const data = await api(url);
    setTransData(data);
    setTransPage(page);
    setViewingTranscription(filename);
  };

  const parseTimeToSecs = (str) => {
    const parts = str.split(':').map(Number);
    if (parts.length === 3) return parts[0]*3600 + parts[1]*60 + parts[2];
    if (parts.length === 2) return parts[0]*60 + parts[1];
    return parseFloat(str) || 0;
  };

  const loadAnalytics = async (filename) => {
    const data = await api(`/api/videos/${encodeURIComponent(filename)}/analytics`);
    setAnalytics(data);
    setViewingAnalytics(filename);
  };

  const exportToExcel = () => {
    if (!analytics) return;
    const wb = XLSX.utils.book_new();

    // Sheet 1: Summary
    const summary = [
      ['Video', analytics.video],
      ['Duración', analytics.duration_fmt],
      ['Total Menciones', analytics.total_mentions],
      ['Tiempo Real Menciones (s)', analytics.total_mention_duration || 0],
      ['Total Marcas', analytics.total_brands],
      ['Cobertura (%)', analytics.coverage_pct],
      ['Procesado', analytics.processed_at],
    ];
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(summary), 'Resumen');

    // Sheet 2: Brands detail
    const brandsData = [['Marca', 'Menciones', 'Duración Total (s)', 'Duración Promedio (s)', 'Primera Mención', 'Última Mención']];
    (analytics.brand_details || []).forEach(b => {
      brandsData.push([b.name, b.count, b.total_duration || 0, b.avg_duration || 0, b.first_mention, b.last_mention]);
    });
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(brandsData), 'Marcas');

    // Sheet 3: Timeline
    const timeData = [['Intervalo', 'Total', ...(analytics.brand_names || [])]];
    (analytics.timeline || []).forEach(t => {
      timeData.push([t.time, t.total, ...(analytics.brand_names || []).map(n => t[n] || 0)]);
    });
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(timeData), 'Timeline');

    XLSX.writeFile(wb, `analytics_${analytics.video.replace(/\.[^.]+$/, '')}.xlsx`);
  };

  if (loading) return <div className="page"><div className="loading">Escaneando carpeta de videos...</div></div>;

  // ANALYTICS DASHBOARD VIEW
  if (viewingAnalytics && analytics && analytics.status !== 'not_processed') {
    const COLORS_CHART = ['#6c5ce7','#00b894','#ff6b6b','#ffd43b','#e17055','#0984e3','#22d3ee','#f06595','#20c997','#ff922b'];
    const pieData = (analytics.brands_chart || []).map((b, i) => ({...b, fill: b.color || COLORS_CHART[i % COLORS_CHART.length]}));
    return (
      <div className="page page-wide">
        <div className="page-header">
          <div><h1>📊 Analítica: {viewingAnalytics.replace(/\.[^.]+$/, '')}</h1><p>Dashboard de menciones de audio</p></div>
          <div style={{display:'flex', gap: 8}}>
            <button className="btn-primary" onClick={exportToExcel}>⬇ Exportar Excel</button>
            <button className="btn-secondary" onClick={() => { setViewingAnalytics(null); setAnalytics(null); }}>← Volver</button>
          </div>
        </div>

        <div className="analytics-cards">
          <div className="analytics-card"><div className="analytics-card-value">{analytics.total_mentions}</div><div className="analytics-card-label">Menciones Totales</div></div>
          <div className="analytics-card"><div className="analytics-card-value">{analytics.total_brands}</div><div className="analytics-card-label">Marcas Detectadas</div></div>
          <div className="analytics-card"><div className="analytics-card-value">{analytics.duration_fmt}</div><div className="analytics-card-label">Duración Video</div></div>
          <div className="analytics-card"><div className="analytics-card-value">{analytics.total_mention_duration || 0}s</div><div className="analytics-card-label">Tiempo Real Menciones</div></div>
          <div className="analytics-card"><div className="analytics-card-value">{analytics.coverage_pct}%</div><div className="analytics-card-label">Cobertura</div></div>
        </div>

        <div className="analytics-row">
          <div className="card analytics-chart-card" style={{flex: 2}}>
            <h3>Menciones por Marca</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={analytics.brands_chart || []} margin={{top: 10, right: 20, left: 0, bottom: 5}}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3a" />
                <XAxis dataKey="name" tick={{fill: '#9898b0', fontSize: 11}} angle={-25} textAnchor="end" height={60} />
                <YAxis tick={{fill: '#9898b0', fontSize: 11}} />
                <Tooltip contentStyle={{background: '#15151e', border: '1px solid #2a2a3a', borderRadius: 8, color: '#eaeaf2'}} itemStyle={{color: '#eaeaf2'}} labelStyle={{color: '#eaeaf2', fontWeight: 'bold'}} />
                <Bar dataKey="mentions" radius={[4, 4, 0, 0]}>
                  {(analytics.brands_chart || []).map((b, i) => <Cell key={i} fill={b.color || COLORS_CHART[i % COLORS_CHART.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="card analytics-chart-card" style={{flex: 1}}>
            <h3>Distribución</h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie data={pieData} dataKey="mentions" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({name, percent}) => `${name} ${(percent*100).toFixed(0)}%`} labelLine={true}>
                  {pieData.map((b, i) => <Cell key={i} fill={b.fill} />)}
                </Pie>
                <Tooltip contentStyle={{background: '#15151e', border: '1px solid #2a2a3a', borderRadius: 8, color: '#eaeaf2'}} itemStyle={{color: '#eaeaf2'}} labelStyle={{color: '#eaeaf2', fontWeight: 'bold'}} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card analytics-chart-card">
          <h3>Timeline de Menciones (intervalos de 5 min)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={analytics.timeline || []} margin={{top: 10, right: 20, left: 0, bottom: 5}}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3a" />
              <XAxis dataKey="time" tick={{fill: '#9898b0', fontSize: 10}} />
              <YAxis tick={{fill: '#9898b0', fontSize: 11}} />
              <Tooltip contentStyle={{background: '#15151e', border: '1px solid #2a2a3a', borderRadius: 8, color: '#eaeaf2'}} itemStyle={{color: '#eaeaf2'}} labelStyle={{color: '#eaeaf2', fontWeight: 'bold'}} />
              <Legend />
              {(analytics.brand_names || []).map((name, i) => (
                <Area key={name} type="monotone" dataKey={name} stackId="1" fill={COLORS_CHART[i % COLORS_CHART.length]} stroke={COLORS_CHART[i % COLORS_CHART.length]} fillOpacity={0.6} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card" style={{marginTop: 16}}>
          <h3>Detalle por Marca</h3>
          <div className="analytics-table">
            <div className="analytics-table-header">
              <span>Marca</span><span>Menciones</span><span>Duración Total</span><span>Dur. Promedio</span><span>Primera</span><span>Última</span>
            </div>
            {(analytics.brand_details || []).sort((a,b) => b.count - a.count).map(b => (
              <div className="analytics-table-row" key={b.name}>
                <span><div className="analytics-dot" style={{background: b.color}}></div>{b.name}</span>
                <span className="mono">{b.count}</span>
                <span className="mono">{b.total_duration || 0}s</span>
                <span className="mono">{b.avg_duration || 0}s</span>
                <span className="mono">{b.first_mention}</span>
                <span className="mono">{b.last_mention}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // TRANSCRIPTION VIEW
  if (viewingTranscription && transData) {
    return (
      <div className="page">
        <div className="page-header">
          <div><h1>Transcripción: {viewingTranscription.replace(/\.[^.]+$/, '')}</h1>
          <p>{transData.total} segmentos · Idioma: {transData.language || '?'}</p></div>
          <button className="btn-secondary" onClick={() => { setViewingTranscription(null); setTransData(null); setTransSearch(''); setTransStartTime(''); setTransEndTime(''); }}>← Volver a Videos</button>
        </div>
        <div className="card" style={{marginBottom: 16}}>
          <div className="form-row" style={{marginBottom: 0}}>
            <div className="form-group"><label>Buscar texto</label><input placeholder="Buscar en transcripción..." value={transSearch} onChange={e => setTransSearch(e.target.value)} onKeyDown={e => { if(e.key==='Enter') loadTranscription(viewingTranscription, 1); }} /></div>
            <div className="form-group" style={{maxWidth: 130}}><label>Desde (hh:mm:ss)</label><input placeholder="00:00:00" value={transStartTime} onChange={e => setTransStartTime(e.target.value)} /></div>
            <div className="form-group" style={{maxWidth: 130}}><label>Hasta (hh:mm:ss)</label><input placeholder="01:30:00" value={transEndTime} onChange={e => setTransEndTime(e.target.value)} /></div>
            <div className="form-group" style={{maxWidth: 100, justifyContent: 'flex-end'}}><button className="btn-primary btn-sm" onClick={() => loadTranscription(viewingTranscription, 1)}>Filtrar</button></div>
          </div>
        </div>
        <div className="trans-list">
          {transData.segments?.map((s, i) => (
            <div className="trans-item" key={i}>
              <span className="trans-time">{s.start_fmt}</span>
              <span className="trans-text">{s.text}</span>
            </div>
          ))}
          {transData.segments?.length === 0 && <div className="empty-text">No hay segmentos para este filtro</div>}
        </div>
        {transData.total_pages > 1 && (
          <div className="frames-pagination">
            <button className="btn-sm btn-secondary" disabled={transPage <= 1} onClick={() => loadTranscription(viewingTranscription, transPage - 1)}>← Anterior</button>
            <span className="pagination-info">Página {transPage} de {transData.total_pages}</span>
            <button className="btn-sm btn-secondary" disabled={transPage >= transData.total_pages} onClick={() => loadTranscription(viewingTranscription, transPage + 1)}>Siguiente →</button>
          </div>
        )}
      </div>
    );
  }

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
              {info.total_duration > 0 && <span className="badge">{info.total_duration}s total</span>}
            </div>
            <div className="mention-list">
              {info.mentions?.map((m, i) => (
                <div className="mention-item" key={i}>
                  <span className="mention-time">{m.start_fmt}</span>
                  <span className="mention-duration">{m.duration ? `${m.duration}s` : ''}</span>
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
      <div className="page page-wide">
        <div className="page-header">
          <div><h1>Frames: {viewingFrames}</h1><p>{framesTotal} imágenes extraídas</p></div>
          <div style={{display:'flex', gap: 8}}>
            <button className="btn-primary btn-sm" onClick={() => { setShowCvatForm(true); setCvatTaskName(viewingFrames); }}>📤 Crear tarea CVAT</button>
            <button className="btn-secondary btn-sm" onClick={() => { setViewingFrames(null); setFrames([]); setSelectedFrames(new Set()); }}>← Volver</button>
          </div>
        </div>

        {showCvatForm && (
          <div className="card" style={{marginBottom: 16}}>
            <h3>Crear Tarea en CVAT</h3>
            <p className="empty-text">Los {framesTotal} frames se subirán directamente a CVAT (servidor a servidor, sin pasar por el navegador).</p>
            <div className="form-row" style={{marginTop: 12}}>
              <div className="form-group"><label>Nombre de la tarea</label><input value={cvatTaskName} onChange={e => setCvatTaskName(e.target.value)} /></div>
              <div className="form-group"><label>Labels (separados por coma)</label><input placeholder="caixabank_valla, caixabank_camiseta" onChange={e => setCvatLabels(e.target.value.split(',').map(s => s.trim()).filter(Boolean))} /></div>
            </div>
            <div className="form-actions">
              <button className="btn-primary btn-sm" onClick={createCvatTask}>Crear y subir frames</button>
              <button className="btn-secondary btn-sm" onClick={() => setShowCvatForm(false)}>Cancelar</button>
            </div>
          </div>
        )}

        <div className="frames-toolbar">
          <div style={{display:'flex', gap: 8, alignItems:'center'}}>
            <button className="btn-sm btn-secondary" onClick={selectAllFrames}>Seleccionar todo</button>
            <button className="btn-sm btn-secondary" onClick={deselectAll}>Deseleccionar</button>
            {selectedFrames.size > 0 && (
              <button className="btn-sm btn-danger" onClick={deleteSelectedFrames}>🗑 Eliminar {selectedFrames.size} seleccionados</button>
            )}
          </div>
          <span className="pagination-info">{selectedFrames.size > 0 ? `${selectedFrames.size} seleccionados` : ''}</span>
        </div>

        <div className="frames-grid">
          {frames.map(f => (
            <div className={`frame-card ${selectedFrames.has(f.name) ? 'frame-selected' : ''}`} key={f.name}>
              <div className="frame-check" onClick={() => toggleFrame(f.name)}>
                <input type="checkbox" checked={selectedFrames.has(f.name)} readOnly />
              </div>
              <img src={f.url} alt={f.name} loading="lazy" onClick={() => toggleFrame(f.name)} />
              <div className="frame-footer">
                <span className="frame-name">{f.name}</span>
                <button className="btn-icon-sm" onClick={() => deleteSingleFrame(viewingFrames, f.name)} title="Eliminar">✕</button>
              </div>
            </div>
          ))}
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
        <code>\\10.43.13.186\Compartida\videos\</code>
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
                <button className="btn-sm btn-secondary" onClick={() => loadTranscription(v.name)}>📝 Transcripción</button>
                <button className="btn-sm btn-secondary" onClick={() => loadMentions(v.name)}>📋 Menciones</button>
                <button className="btn-sm btn-primary" onClick={() => loadAnalytics(v.name)}>📊 Analítica</button>
                <button className="btn-sm btn-secondary" onClick={async () => { const r = await api(`/api/videos/${encodeURIComponent(v.name)}/sync-sqlserver`, {method:'POST'}); alert(r?.status === 'ok' ? `✓ Sincronizado: ${r.mentions} menciones, ${r.segments} segmentos` : `✕ Error: ${r?.message || 'No se pudo conectar'}`); }}>🔄 SQL Server</button>
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
