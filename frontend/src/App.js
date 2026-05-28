import React, { useState, useEffect, createContext, useContext } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate, useLocation } from 'react-router-dom';
import './styles/App.css';

// ==============================================
//  API HELPER
// ==============================================
const API = process.env.REACT_APP_API_URL || '';

async function api(path, options = {}) {
  const token = localStorage.getItem('token');
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (res.status === 401) {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
    return null;
  }
  return res.json();
}

// ==============================================
//  AUTH CONTEXT
// ==============================================
const AuthContext = createContext(null);

function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('user');
    return saved ? JSON.parse(saved) : null;
  });

  const login = async (username, password) => {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    if (data?.access_token) {
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      setUser(data.user);
      return true;
    }
    return false;
  };

  const logout = () => {
    api('/api/auth/logout', { method: 'POST' });
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

function useAuth() { return useContext(AuthContext); }

// ==============================================
//  LOGIN PAGE
// ==============================================
function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    const ok = await login(username, password);
    setLoading(false);
    if (ok) navigate('/');
    else setError('Credenciales incorrectas');
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <div className="login-icon">G</div>
          <h1>GECA Brands</h1>
          <p>Gestión de marcas para detección en video</p>
        </div>
        <form onSubmit={handleSubmit}>
          {error && <div className="error-msg">{error}</div>}
          <div className="form-group">
            <label>Usuario</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" required />
          </div>
          <div className="form-group">
            <label>Contraseña</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••" required />
          </div>
          <button type="submit" className="btn-primary btn-full" disabled={loading}>
            {loading ? 'Entrando...' : 'Iniciar Sesión'}
          </button>
        </form>
        <div className="login-footer">
          <span>Admin por defecto: admin / admin123</span>
        </div>
      </div>
    </div>
  );
}

// ==============================================
//  LAYOUT
// ==============================================
function Layout({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: '◆' },
    { path: '/brands', label: 'Marcas', icon: '◎' },
    { path: '/contexts', label: 'Contextos', icon: '▦' },
    { path: '/cvat', label: 'CVAT', icon: '⬡' },
  ];

  if (user?.role === 'admin') {
    navItems.push({ path: '/users', label: 'Usuarios', icon: '◇' });
  }

  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-icon">G</div>
          <span className="brand-text">GECA</span>
        </div>
        <div className="sidebar-nav">
          {navItems.map(item => (
            <Link
              key={item.path}
              to={item.path}
              className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </Link>
          ))}
        </div>
        <div className="sidebar-footer">
          <div className="user-info">
            <div className="user-avatar">{user?.username?.[0]?.toUpperCase()}</div>
            <div className="user-details">
              <span className="user-name">{user?.username}</span>
              <span className="user-role">{user?.role}</span>
            </div>
          </div>
          <button className="btn-logout" onClick={logout}>Salir</button>
        </div>
      </nav>
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}

// ==============================================
//  DASHBOARD PAGE
// ==============================================
function DashboardPage() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api('/api/stats').then(setStats);
  }, []);

  if (!stats) return <div className="page"><div className="loading">Cargando...</div></div>;

  const cards = [
    { label: 'Marcas', value: stats.total_brands, icon: '◎', color: '#6c5ce7' },
    { label: 'Submarcas', value: stats.total_subbrands, icon: '◈', color: '#00b894' },
    { label: 'Contextos', value: stats.total_contexts, icon: '▦', color: '#e17055' },
    { label: 'Usuarios', value: stats.total_users, icon: '◇', color: '#0984e3' },
  ];

  return (
    <div className="page">
      <div className="page-header">
        <h1>Dashboard</h1>
        <p>Resumen del sistema de gestión de marcas</p>
      </div>
      <div className="stats-grid">
        {cards.map(card => (
          <div className="stat-card" key={card.label} style={{ '--accent': card.color }}>
            <div className="stat-icon">{card.icon}</div>
            <div className="stat-value">{card.value}</div>
            <div className="stat-label">{card.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ==============================================
//  BRANDS PAGE
// ==============================================
function BrandsPage() {
  const [brands, setBrands] = useState([]);
  const [contexts, setContexts] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [showSubForm, setShowSubForm] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [form, setForm] = useState({ name: '', display_name: '', color: '#6c5ce7', client: '' });
  const [subForm, setSubForm] = useState({ context_id: '', cvat_label: '', description: '', min_training_images: 200 });

  const load = () => {
    api('/api/brands').then(setBrands);
    api('/api/contexts').then(setContexts);
  };

  useEffect(load, []);

  const createBrand = async (e) => {
    e.preventDefault();
    await api('/api/brands', { method: 'POST', body: JSON.stringify(form) });
    setForm({ name: '', display_name: '', color: '#6c5ce7', client: '' });
    setShowForm(false);
    load();
  };

  const deleteBrand = async (id) => {
    if (window.confirm('¿Eliminar esta marca y todas sus submarcas?')) {
      await api(`/api/brands/${id}`, { method: 'DELETE' });
      load();
    }
  };

  const createSubBrand = async (e, brandId) => {
    e.preventDefault();
    await api('/api/subbrands', {
      method: 'POST',
      body: JSON.stringify({ ...subForm, brand_id: brandId, context_id: parseInt(subForm.context_id) }),
    });
    setSubForm({ context_id: '', cvat_label: '', description: '', min_training_images: 200 });
    setShowSubForm(null);
    load();
  };

  const deleteSubBrand = async (id) => {
    if (window.confirm('¿Eliminar esta submarca?')) {
      await api(`/api/subbrands/${id}`, { method: 'DELETE' });
      load();
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Marcas</h1>
          <p>Gestiona marcas y sus variantes por contexto</p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>+ Nueva Marca</button>
      </div>

      {showForm && (
        <div className="card form-card">
          <h3>Nueva Marca</h3>
          <form onSubmit={createBrand}>
            <div className="form-row">
              <div className="form-group">
                <label>Nombre (ID)</label>
                <input placeholder="cocacola" value={form.name} onChange={e => setForm({...form, name: e.target.value})} required />
              </div>
              <div className="form-group">
                <label>Nombre Display</label>
                <input placeholder="Coca-Cola" value={form.display_name} onChange={e => setForm({...form, display_name: e.target.value})} required />
              </div>
              <div className="form-group">
                <label>Cliente</label>
                <input placeholder="The Coca-Cola Company" value={form.client} onChange={e => setForm({...form, client: e.target.value})} />
              </div>
              <div className="form-group" style={{maxWidth: 100}}>
                <label>Color</label>
                <input type="color" value={form.color} onChange={e => setForm({...form, color: e.target.value})} />
              </div>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn-primary">Crear</button>
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancelar</button>
            </div>
          </form>
        </div>
      )}

      <div className="brands-list">
        {brands.map(brand => (
          <div className="card brand-card" key={brand.id}>
            <div className="brand-header" onClick={() => setExpanded(expanded === brand.id ? null : brand.id)}>
              <div className="brand-color" style={{ background: brand.color }}></div>
              <div className="brand-info">
                <h3>{brand.display_name}</h3>
                <span className="brand-meta">{brand.name} · {brand.client || 'Sin cliente'}</span>
              </div>
              <div className="brand-badges">
                <span className="badge">{brand.subbrands?.length || 0} submarcas</span>
              </div>
              <span className={`expand-icon ${expanded === brand.id ? 'open' : ''}`}>▸</span>
            </div>

            {expanded === brand.id && (
              <div className="brand-body">
                <div className="subbrands-list">
                  {brand.subbrands?.map(sb => (
                    <div className="subbrand-item" key={sb.id}>
                      <span className="subbrand-context">{sb.context_icon} {sb.context}</span>
                      <code className="subbrand-label">{sb.cvat_label}</code>
                      <span className={`status ${sb.is_active ? 'active' : 'inactive'}`}>
                        {sb.is_active ? 'Activo' : 'Inactivo'}
                      </span>
                      <button className="btn-icon btn-danger-icon" onClick={() => deleteSubBrand(sb.id)}>✕</button>
                    </div>
                  ))}
                  {(!brand.subbrands || brand.subbrands.length === 0) && (
                    <p className="empty-text">No hay submarcas. Agrega una para empezar a anotar.</p>
                  )}
                </div>

                {showSubForm === brand.id ? (
                  <form className="subbrand-form" onSubmit={(e) => createSubBrand(e, brand.id)}>
                    <div className="form-row">
                      <div className="form-group">
                        <label>Contexto</label>
                        <select value={subForm.context_id} onChange={e => setSubForm({...subForm, context_id: e.target.value})} required>
                          <option value="">Seleccionar...</option>
                          {contexts.map(c => (
                            <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
                          ))}
                        </select>
                      </div>
                      <div className="form-group">
                        <label>Label CVAT</label>
                        <input placeholder={`${brand.name}_camiseta`} value={subForm.cvat_label}
                          onChange={e => setSubForm({...subForm, cvat_label: e.target.value})} required />
                      </div>
                      <div className="form-group">
                        <label>Mín. imágenes</label>
                        <input type="number" value={subForm.min_training_images}
                          onChange={e => setSubForm({...subForm, min_training_images: parseInt(e.target.value)})} />
                      </div>
                    </div>
                    <div className="form-actions">
                      <button type="submit" className="btn-primary btn-sm">Agregar</button>
                      <button type="button" className="btn-secondary btn-sm" onClick={() => setShowSubForm(null)}>Cancelar</button>
                    </div>
                  </form>
                ) : (
                  <div className="brand-actions">
                    <button className="btn-secondary btn-sm" onClick={() => setShowSubForm(brand.id)}>+ Submarca</button>
                    <button className="btn-danger btn-sm" onClick={() => deleteBrand(brand.id)}>Eliminar marca</button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {brands.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">◎</div>
            <p>No hay marcas registradas</p>
            <button className="btn-primary" onClick={() => setShowForm(true)}>Crear primera marca</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ==============================================
//  CONTEXTS PAGE
// ==============================================
function ContextsPage() {
  const [contexts, setContexts] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', icon: '' });

  const load = () => api('/api/contexts').then(setContexts);
  useEffect(load, []);

  const create = async (e) => {
    e.preventDefault();
    await api('/api/contexts', { method: 'POST', body: JSON.stringify(form) });
    setForm({ name: '', description: '', icon: '' });
    setShowForm(false);
    load();
  };

  const remove = async (id) => {
    if (window.confirm('¿Eliminar este contexto?')) {
      await api(`/api/contexts/${id}`, { method: 'DELETE' });
      load();
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Contextos</h1>
          <p>Superficies donde aparecen las marcas</p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>+ Nuevo Contexto</button>
      </div>

      {showForm && (
        <div className="card form-card">
          <h3>Nuevo Contexto</h3>
          <form onSubmit={create}>
            <div className="form-row">
              <div className="form-group" style={{maxWidth: 80}}>
                <label>Icono</label>
                <input placeholder="👕" value={form.icon} onChange={e => setForm({...form, icon: e.target.value})} />
              </div>
              <div className="form-group">
                <label>Nombre</label>
                <input placeholder="camiseta" value={form.name} onChange={e => setForm({...form, name: e.target.value})} required />
              </div>
              <div className="form-group" style={{flex: 2}}>
                <label>Descripción</label>
                <input placeholder="Logo en camiseta de jugador" value={form.description} onChange={e => setForm({...form, description: e.target.value})} />
              </div>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn-primary">Crear</button>
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancelar</button>
            </div>
          </form>
        </div>
      )}

      <div className="contexts-grid">
        {contexts.map(ctx => (
          <div className="card context-card" key={ctx.id}>
            <div className="context-icon">{ctx.icon || '▦'}</div>
            <h3>{ctx.name}</h3>
            <p>{ctx.description || 'Sin descripción'}</p>
            <button className="btn-icon btn-danger-icon" onClick={() => remove(ctx.id)}>✕</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ==============================================
//  CVAT PAGE
// ==============================================
function CVATPage() {
  const [tasks, setTasks] = useState([]);
  const [subbrands, setSubbrands] = useState([]);
  const [labelStats, setLabelStats] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api('/api/cvat/tasks'),
      api('/api/subbrands'),
    ]).then(([tasksData, subs]) => {
      setTasks(tasksData?.tasks || []);
      setSubbrands(subs || []);
      setLoading(false);
    });
  }, []);

  const checkLabel = async (label) => {
    setLabelStats(prev => ({ ...prev, [label]: { loading: true } }));
    const stats = await api(`/api/cvat/labels/${label}`);
    setLabelStats(prev => ({ ...prev, [label]: stats }));
  };

  if (loading) return <div className="page"><div className="loading">Conectando con CVAT...</div></div>;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Integración CVAT</h1>
          <p>Estado de los datasets de entrenamiento</p>
        </div>
        <a href={`http://${window.location.hostname}:8080`} target="_blank" rel="noreferrer" className="btn-primary">
          Abrir CVAT ↗
        </a>
      </div>

      <div className="section">
        <h2>Progreso por Submarca</h2>
        <p className="section-desc">Consulta cuántas imágenes anotadas hay para cada label</p>
        <div className="label-check-grid">
          {subbrands.map(sb => {
            const stats = labelStats[sb.cvat_label];
            return (
              <div className="card label-card" key={sb.id}>
                <div className="label-header">
                  <code>{sb.cvat_label}</code>
                  <button className="btn-sm btn-secondary" onClick={() => checkLabel(sb.cvat_label)}>
                    {stats?.loading ? '...' : 'Consultar'}
                  </button>
                </div>
                {stats && !stats.loading && (
                  <div className="label-stats">
                    <div className="progress-bar">
                      <div className="progress-fill" style={{ width: `${stats.progress_pct || 0}%` }}></div>
                    </div>
                    <div className="progress-info">
                      <span>{stats.total_images || 0} / {stats.min_required || 200} imágenes</span>
                      <span className={stats.ready_to_train ? 'text-green' : 'text-orange'}>
                        {stats.ready_to_train ? '✓ Listo' : 'Anotando...'}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {subbrands.length === 0 && (
            <div className="empty-text">Crea marcas y submarcas primero para ver el progreso</div>
          )}
        </div>
      </div>

      <div className="section">
        <h2>Tareas CVAT</h2>
        <div className="tasks-list">
          {tasks.map(t => (
            <div className="card task-card" key={t.id}>
              <div className="task-info">
                <h4>{t.name}</h4>
                <span className="task-meta">{t.size} frames · {t.labels?.join(', ') || 'sin labels'}</span>
              </div>
              <span className={`status ${t.status}`}>{t.status}</span>
            </div>
          ))}
          {tasks.length === 0 && <div className="empty-text">No hay tareas en CVAT o no se pudo conectar</div>}
        </div>
      </div>
    </div>
  );
}

// ==============================================
//  USERS PAGE (admin only)
// ==============================================
function UsersPage() {
  const [users, setUsers] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'annotator' });

  const load = () => api('/api/users').then(data => { if (data) setUsers(data); });
  useEffect(load, []);

  const create = async (e) => {
    e.preventDefault();
    await api('/api/users', { method: 'POST', body: JSON.stringify(form) });
    setForm({ username: '', email: '', password: '', role: 'annotator' });
    setShowForm(false);
    load();
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Usuarios</h1>
          <p>Gestión de accesos al sistema</p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>+ Nuevo Usuario</button>
      </div>

      {showForm && (
        <div className="card form-card">
          <h3>Nuevo Usuario</h3>
          <form onSubmit={create}>
            <div className="form-row">
              <div className="form-group">
                <label>Usuario</label>
                <input value={form.username} onChange={e => setForm({...form, username: e.target.value})} required />
              </div>
              <div className="form-group">
                <label>Email</label>
                <input type="email" value={form.email} onChange={e => setForm({...form, email: e.target.value})} required />
              </div>
              <div className="form-group">
                <label>Contraseña</label>
                <input type="password" value={form.password} onChange={e => setForm({...form, password: e.target.value})} required />
              </div>
              <div className="form-group">
                <label>Rol</label>
                <select value={form.role} onChange={e => setForm({...form, role: e.target.value})}>
                  <option value="admin">Admin</option>
                  <option value="annotator">Anotador</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn-primary">Crear</button>
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancelar</button>
            </div>
          </form>
        </div>
      )}

      <div className="users-list">
        {users.map(u => (
          <div className="card user-card" key={u.id}>
            <div className="user-card-avatar">{u.username[0].toUpperCase()}</div>
            <div className="user-card-info">
              <h4>{u.username}</h4>
              <span>{u.email}</span>
            </div>
            <span className={`badge role-${u.role}`}>{u.role}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ==============================================
//  PROTECTED ROUTE
// ==============================================
function ProtectedRoute({ children }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" />;
  return <Layout>{children}</Layout>;
}

// ==============================================
//  APP
// ==============================================
function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          <Route path="/brands" element={<ProtectedRoute><BrandsPage /></ProtectedRoute>} />
          <Route path="/contexts" element={<ProtectedRoute><ContextsPage /></ProtectedRoute>} />
          <Route path="/cvat" element={<ProtectedRoute><CVATPage /></ProtectedRoute>} />
          <Route path="/users" element={<ProtectedRoute><UsersPage /></ProtectedRoute>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
