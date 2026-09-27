/// <reference types="vite/client" />
import { useContext } from 'react';
import { AuthContext } from '../context/AuthContextDef';

// 下位互換性のためにラッパーとしてエクスポート
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuthはAuthProviderの中で使用する必要があります');
  }
  return context;
};
