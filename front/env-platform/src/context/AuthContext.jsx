import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token') || null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // In a real app, you might validate the token with the backend here
    if (token) {
      setUser({ email: 'user@example.com', name: 'Demo User' });
    }
    setLoading(false);
  }, [token]);

  const login = async (email, password) => {
    // Mock API call
    console.log('Logging in with', email, password);
    const mockToken = 'mock-jwt-token-123';
    setToken(mockToken);
    localStorage.setItem('token', mockToken);
    setUser({ email, name: 'Demo User' });
    return true;
  };

  const signup = async (email, password, name) => {
    // Mock API call
    console.log('Signing up with', email, password, name);
    const mockToken = 'mock-jwt-token-123';
    setToken(mockToken);
    localStorage.setItem('token', mockToken);
    setUser({ email, name });
    return true;
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('token');
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, logout }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
