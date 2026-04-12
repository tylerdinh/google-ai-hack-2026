import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL  = 'https://esfsyvcftnriqftgkvvp.supabase.co'
const SUPABASE_ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzZnN5dmNmdG5yaXFmdGdrdnZwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU5Mzk4MDYsImV4cCI6MjA5MTUxNTgwNn0.o2qvQIK51_qChj6ecg0aCVZ3rcWryg_XwxWgN7S9mRM'

export const sb = createClient(SUPABASE_URL, SUPABASE_ANON)