import { createContext } from 'react';
import { AuthContextType } from './AuthContext.types';

// AuthContext の定義
export const AuthContext = createContext<AuthContextType | undefined>(undefined);
