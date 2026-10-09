import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api, type Profile, type Schema } from "./api";
import { Layout } from "./components/common";
import { AccuracyPage } from "./pages/AccuracyPage";
import { CustomerPage } from "./pages/CustomerPage";
import { FeedPage } from "./pages/FeedPage";
import { ProfilePage } from "./pages/ProfilePage";
import { QuickPage } from "./pages/QuickPage";
import { TenderPage } from "./pages/TenderPage";
import { UploadPage } from "./pages/UploadPage";

interface Ctx {
  profile: Profile | null;
  schema: Schema | null;
  reloadProfile: () => Promise<void>;
}

const AppContext = createContext<Ctx>({ profile: null, schema: null, reloadProfile: async () => {} });
export const useApp = () => useContext(AppContext);

export function App() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);

  const reloadProfile = useCallback(async () => {
    setProfile(await api.profile(1));
  }, []);

  useEffect(() => {
    reloadProfile().catch(() => setProfile(null));
    api.schema().then(setSchema).catch(() => setSchema(null));
  }, [reloadProfile]);

  const company = profile?.company
    ? { name: profile.company.name, inn: profile.company.inn, is_msp: profile.company.is_msp }
    : null;

  return (
    <AppContext.Provider value={{ profile, schema, reloadProfile }}>
      <Layout company={company}>
        <Routes>
          <Route path="/" element={<FeedPage />} />
          <Route path="/quick" element={<QuickPage />} />
          <Route path="/tenders/:id" element={<TenderPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/accuracy" element={<AccuracyPage />} />
          <Route path="/customer" element={<CustomerPage />} />
          <Route path="*" element={<FeedPage />} />
        </Routes>
      </Layout>
    </AppContext.Provider>
  );
}
