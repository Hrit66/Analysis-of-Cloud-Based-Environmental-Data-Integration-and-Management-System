import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { API_BASE, authHeaders } from '../lib/api';
import { Building2, Mail, ShieldCheck, Trash2, UserPlus, Users } from 'lucide-react';

const ROLE_OPTIONS = ['viewer', 'analyst', 'org_admin'];

const OrganizationPage = () => {
  const { user } = useAuth();
  const [org, setOrg] = useState(null);
  const [members, setMembers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [inviteForm, setInviteForm] = useState({ email: '', org_role: 'viewer' });
  const [devInvite, setDevInvite] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError('');
    setLoading(true);
    try {
      const headers = authHeaders();
      const meRes = await fetch(`${API_BASE}/organizations/me`, { headers });
      if (meRes.status === 404) {
        setOrg(null);
        return;
      }
      if (!meRes.ok) throw new Error('Could not load your organization');
      const orgData = await meRes.json();
      setOrg(orgData);
      if (user?.org_role === 'org_admin' || user?.platform_role === 'platform_admin') {
        const [membersRes, invitesRes] = await Promise.all([
          fetch(`${API_BASE}/organizations/${orgData.id}/members`, { headers }),
          fetch(`${API_BASE}/organizations/${orgData.id}/invites`, { headers }),
        ]);
        if (membersRes.ok) setMembers(await membersRes.json());
        if (invitesRes.ok) setInvites(await invitesRes.json());
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  const createInvite = async (e) => {
    e.preventDefault();
    setError('');
    setDevInvite('');
    try {
      const res = await fetch(`${API_BASE}/organizations/${org.id}/invites`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(inviteForm),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not create invitation');
      setInviteForm({ email: '', org_role: 'viewer' });
      if (body.token) setDevInvite(`/accept-invite?token=${body.token}`);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const updateRole = async (member, orgRole) => {
    setError('');
    try {
      const res = await fetch(`${API_BASE}/organizations/${org.id}/members/${member.user_id}`, {
        method: 'PATCH',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ org_role: orgRole }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not update role');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeMember = async (member) => {
    if (!window.confirm(`Remove ${member.email} from the organization?`)) return;
    setError('');
    try {
      const res = await fetch(`${API_BASE}/organizations/${org.id}/members/${member.user_id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not remove member');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const revokeInvite = async (inviteId) => {
    setError('');
    try {
      const res = await fetch(`${API_BASE}/organizations/${org.id}/invites/${inviteId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error('Could not revoke invitation');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) {
    return <div className="p-6 text-slate-600">Loading organization...</div>;
  }

  if (!org) {
    return (
      <div className="mx-auto max-w-2xl glass-panel p-8 text-center">
        <Building2 className="mx-auto h-10 w-10 text-blue-600" />
        <h1 className="mt-4 text-2xl font-bold text-slate-900">No organization membership</h1>
        <p className="mt-2 text-sm text-slate-600">Apply for an organization account or accept an invitation.</p>
        <Link to="/organization/apply" className="mt-4 inline-block rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white">
          Apply for an organization
        </Link>
      </div>
    );
  }

  const canManage = user?.org_role === 'org_admin' || user?.platform_role === 'platform_admin';

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="glass-panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{org.name}</h1>
            <p className="mt-1 text-sm text-slate-600">{org.domains?.join(', ')}</p>
            <p className="text-sm text-slate-500">{org.contact_email}</p>
          </div>
          <div className="flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-sm text-emerald-700">
            <ShieldCheck className="h-4 w-4" /> {org.status}
          </div>
        </div>
      </div>

      {error && <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">{error}</div>}

      {canManage && (
        <>
          <div className="glass-panel p-6">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <UserPlus className="h-5 w-5 text-blue-600" /> Invite staff
            </h2>
            <form className="mt-4 flex flex-col gap-3 sm:flex-row" onSubmit={createInvite}>
              <div className="relative flex-1">
                <Mail className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                <input
                  type="email"
                  required
                  value={inviteForm.email}
                  onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                  placeholder="colleague@organization.org"
                  className="w-full rounded-xl border border-white/60 bg-white/40 p-2.5 pl-9 text-sm"
                />
              </div>
              <select
                value={inviteForm.org_role}
                onChange={(e) => setInviteForm({ ...inviteForm, org_role: e.target.value })}
                className="rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm"
              >
                {ROLE_OPTIONS.map((role) => <option key={role} value={role}>{role.replace('_', ' ')}</option>)}
              </select>
              <button type="submit" className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white">Send invite</button>
            </form>
            {devInvite && <Link to={devInvite} className="mt-3 block text-sm text-blue-600">Open development invitation link</Link>}
            {invites.length > 0 && (
              <div className="mt-5 space-y-2">
                {invites.map((invite) => (
                  <div key={invite.id} className="flex items-center justify-between rounded-xl border border-white/60 bg-white/40 px-3 py-2 text-sm">
                    <span>{invite.email} - {invite.org_role.replace('_', ' ')}</span>
                    <button onClick={() => revokeInvite(invite.id)} className="text-red-600" title="Revoke invite">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="glass-panel p-6">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Users className="h-5 w-5 text-blue-600" /> Members
            </h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-500">
                  <tr><th className="py-2">Name</th><th>Email</th><th>Role</th><th>Status</th><th>MFA</th><th></th></tr>
                </thead>
                <tbody>
                  {members.map((member) => (
                    <tr key={member.user_id} className="border-t border-white/50">
                      <td className="py-2">{member.full_name || '-'}</td>
                      <td>{member.email}</td>
                      <td>
                        <select
                          value={member.org_role || 'viewer'}
                          onChange={(e) => updateRole(member, e.target.value)}
                          disabled={member.user_id === user.id}
                          className="rounded-lg border border-white/60 bg-white/40 px-2 py-1 text-sm capitalize disabled:opacity-60"
                        >
                          {ROLE_OPTIONS.map((role) => <option key={role} value={role}>{role.replace('_', ' ')}</option>)}
                        </select>
                      </td>
                      <td>{member.status}</td>
                      <td>{member.mfa_enabled ? 'Enabled' : 'Not enabled'}</td>
                      <td>
                        <button
                          onClick={() => removeMember(member)}
                          disabled={member.user_id === user.id}
                          className="text-red-600 disabled:opacity-30"
                          title="Remove member"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default OrganizationPage;
