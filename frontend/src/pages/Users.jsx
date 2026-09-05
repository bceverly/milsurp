/** User administration: create, edit, reset passwords, deactivate, delete. */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { usePasswordPolicy, useTitle } from "../hooks.js";
import { useAuth } from "../auth.jsx";
import { formatDateTime, formatRelative, timeTitle } from "../format.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { Plus, Refresh, Trash } from "../components/Icons.jsx";

const EMPTY = {
  username: "",
  email: "",
  full_name: "",
  password: "",
  role: "normal",
  is_active: true,
};

/**
 * The create/edit form.
 *
 * There is deliberately no submit button in here: the dialog footer's Save
 * button is associated with this form via `form="user-form"`, which both wires
 * up the click and gives the browser the submit button it needs for
 * Enter-to-submit. A second hidden one would just be a duplicate control that
 * assistive technology announces twice.
 */
function UserForm({ user, onSubmit, error, policy }) {
  const editing = Boolean(user);
  const [form, setForm] = useState(editing ? { ...EMPTY, ...user, password: "" } : EMPTY);

  const set = (key) => (event) => {
    const value =
      event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((current) => ({ ...current, [key]: value }));
  };

  function submit(event) {
    event.preventDefault();
    if (editing) {
      // Only send what changed; an empty password field means "leave it alone".
      const patch = {
        email: form.email,
        full_name: form.full_name || null,
        role: form.role,
        is_active: form.is_active,
      };
      if (form.password) patch.password = form.password;
      onSubmit(patch);
    } else {
      onSubmit({
        ...form,
        full_name: form.full_name || null,
      });
    }
  }

  return (
    <form onSubmit={submit} id="user-form">
      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      {!editing && (
        <Field
          label="Username"
          hint="Letters, numbers, dot, dash and underscore. Cannot be changed later."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={form.username}
              onChange={set("username")}
              required
              minLength={3}
              maxLength={64}
              pattern="[A-Za-z0-9._\-]+"
              autoCapitalize="none"
              autoCorrect="off"
            />
          )}
        </Field>
      )}

      <Field label="Email address" hint="Digest emails are sent here.">
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            type="email"
            value={form.email}
            onChange={set("email")}
            required
          />
        )}
      </Field>

      <label className="field">
        <span className="field__label">Full name (optional)</span>
        <input
          className="input"
          value={form.full_name || ""}
          onChange={set("full_name")}
        />
      </label>

      <Field
        label={editing ? "New password (leave blank to keep)" : "Password"}
        hint={policy.hint}
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            type="password"
            value={form.password}
            onChange={set("password")}
            required={!editing}
            minLength={policy.minLength}
            autoComplete="new-password"
          />
        )}
      </Field>

      <div className="form-row form-row--2">
        <label className="field">
          <span className="field__label">Role</span>
          <select className="select" value={form.role} onChange={set("role")}>
            <option value="normal">Normal — can view listings</option>
            <option value="admin">Admin — full control</option>
          </select>
        </label>

        <label className="field">
          <span className="field__label">Status</span>
          <label className="checkbox" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={form.is_active} onChange={set("is_active")} />
            <span>Account is active</span>
          </label>
        </label>
      </div>
    </form>
  );
}

export default function UsersPage() {
  useTitle("Users");
  const policy = usePasswordPolicy();
  const { user: me } = useAuth();
  const [users, setUsers] = useState(null);
  const [error, setError] = useState(null);
  const [formError, setFormError] = useState(null);
  const [editing, setEditing] = useState(null); // user object, or "new"
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = useCallback(() => {
    api
      .users()
      .then(setUsers)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  async function save(payload) {
    setBusy(true);
    setFormError(null);
    try {
      if (editing === "new") await api.createUser(payload);
      else await api.updateUser(editing.id, payload);
      setEditing(null);
      load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(user) {
    setBusy(true);
    try {
      await api.deleteUser(user.id);
      setConfirmDelete(null);
      load();
    } catch (err) {
      setError(err.message);
      setConfirmDelete(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <p>
            Admins can do everything, including managing accounts. Normal users can view
            listings and set up their own email digest.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
          <button className="btn btn--primary" onClick={() => setEditing("new")}>
            <Plus size={16} />
            Add user
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      <div className="panel">
        {!users && (
          <div className="loading-row" style={{ padding: 20 }}>
            <div className="spinner" />
            Loading users…
          </div>
        )}

        {users && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last sign-in</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.username}</strong>
                      {user.full_name && (
                        <div style={{ fontSize: 12, color: "var(--ink-400)" }}>
                          {user.full_name}
                        </div>
                      )}
                    </td>
                    <td style={{ wordBreak: "break-all" }}>{user.email}</td>
                    <td>
                      <span
                        className={`chip ${
                          user.role === "admin" ? "chip--info" : "chip--neutral"
                        }`}
                      >
                        {user.role === "admin" ? "Admin" : "Normal"}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`chip ${
                          user.is_active ? "chip--success" : "chip--danger"
                        }`}
                      >
                        {user.is_active ? "Active" : "Disabled"}
                      </span>
                    </td>
                    <td title={timeTitle(user.last_login_at)}>
                      {user.last_login_at ? formatRelative(user.last_login_at) : "never"}
                    </td>
                    <td className="table__actions">
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setFormError(null);
                          setEditing(user);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn--ghost btn--sm"
                        style={{ color: "var(--red-600)" }}
                        disabled={user.id === me?.id}
                        title={
                          user.id === me?.id
                            ? "You cannot delete your own account"
                            : "Delete user"
                        }
                        onClick={() => setConfirmDelete(user)}
                      >
                        <Trash size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <Modal
          title={editing === "new" ? "Add user" : `Edit ${editing.username}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button className="btn btn--secondary" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button
                className="btn btn--primary"
                type="submit"
                form="user-form"
                disabled={busy}
              >
                {busy ? "Saving…" : "Save"}
              </button>
            </>
          }
        >
          <UserForm
            user={editing === "new" ? null : editing}
            onSubmit={save}
            error={formError}
            policy={policy}
          />
        </Modal>
      )}

      {confirmDelete && (
        <Modal
          title="Delete user"
          onClose={() => setConfirmDelete(null)}
          footer={
            <>
              <button
                className="btn btn--secondary"
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </button>
              <button
                className="btn btn--danger"
                onClick={() => remove(confirmDelete)}
                disabled={busy}
              >
                Delete permanently
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            Delete <strong>{confirmDelete.username}</strong>? Their digest settings and
            email history are removed too. Listings and scan history are unaffected. This
            cannot be undone.
          </p>
        </Modal>
      )}
    </div>
  );
}
