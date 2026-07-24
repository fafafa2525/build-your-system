export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      apify_keys: {
        Row: {
          added_by: string | null
          added_via: string
          api_key: string
          created_at: string
          daily_reset_at: string
          daily_usage: number
          id: string
          label: string
          last_error: string | null
          last_error_at: string | null
          last_success_at: string | null
          last_used_at: string | null
          monthly_reset_at: string
          monthly_usage: number
          status: Database["public"]["Enums"]["key_status"]
          updated_at: string
          usage_count: number
        }
        Insert: {
          added_by?: string | null
          added_via?: string
          api_key: string
          created_at?: string
          daily_reset_at?: string
          daily_usage?: number
          id?: string
          label: string
          last_error?: string | null
          last_error_at?: string | null
          last_success_at?: string | null
          last_used_at?: string | null
          monthly_reset_at?: string
          monthly_usage?: number
          status?: Database["public"]["Enums"]["key_status"]
          updated_at?: string
          usage_count?: number
        }
        Update: {
          added_by?: string | null
          added_via?: string
          api_key?: string
          created_at?: string
          daily_reset_at?: string
          daily_usage?: number
          id?: string
          label?: string
          last_error?: string | null
          last_error_at?: string | null
          last_success_at?: string | null
          last_used_at?: string | null
          monthly_reset_at?: string
          monthly_usage?: number
          status?: Database["public"]["Enums"]["key_status"]
          updated_at?: string
          usage_count?: number
        }
        Relationships: []
      }
      bot_settings: {
        Row: {
          allowed_telegram_ids: number[]
          auto_send_results: boolean
          default_country: string | null
          default_max_pages: number | null
          id: number
          updated_at: string
        }
        Insert: {
          allowed_telegram_ids?: number[]
          auto_send_results?: boolean
          default_country?: string | null
          default_max_pages?: number | null
          id?: number
          updated_at?: string
        }
        Update: {
          allowed_telegram_ids?: number[]
          auto_send_results?: boolean
          default_country?: string | null
          default_max_pages?: number | null
          id?: number
          updated_at?: string
        }
        Relationships: []
      }
      contact_validations: {
        Row: {
          attempts: number
          checked_at: string | null
          contact_type: string
          contact_value: string
          created_at: string
          error_message: string | null
          expires_at: string | null
          id: string
          result: Json
          source_search_id: string | null
          status: string
          updated_at: string
          validator: string
        }
        Insert: {
          attempts?: number
          checked_at?: string | null
          contact_type: string
          contact_value: string
          created_at?: string
          error_message?: string | null
          expires_at?: string | null
          id?: string
          result?: Json
          source_search_id?: string | null
          status?: string
          updated_at?: string
          validator: string
        }
        Update: {
          attempts?: number
          checked_at?: string | null
          contact_type?: string
          contact_value?: string
          created_at?: string
          error_message?: string | null
          expires_at?: string | null
          id?: string
          result?: Json
          source_search_id?: string | null
          status?: string
          updated_at?: string
          validator?: string
        }
        Relationships: [
          {
            foreignKeyName: "contact_validations_source_search_id_fkey"
            columns: ["source_search_id"]
            isOneToOne: false
            referencedRelation: "searches"
            referencedColumns: ["id"]
          },
        ]
      }
      extracted_numbers: {
        Row: {
          country: string | null
          created_at: string
          email: string | null
          first_search_id: string | null
          first_seen_at: string
          has_website: boolean
          id: string
          is_sent: boolean
          kind: string | null
          last_search_id: string | null
          last_seen_at: string
          notes: string | null
          page_name: string | null
          page_url: string | null
          phone: string
          sent_at: string | null
          times_found: number
          updated_at: string
          website: string | null
        }
        Insert: {
          country?: string | null
          created_at?: string
          email?: string | null
          first_search_id?: string | null
          first_seen_at?: string
          has_website?: boolean
          id?: string
          is_sent?: boolean
          kind?: string | null
          last_search_id?: string | null
          last_seen_at?: string
          notes?: string | null
          page_name?: string | null
          page_url?: string | null
          phone: string
          sent_at?: string | null
          times_found?: number
          updated_at?: string
          website?: string | null
        }
        Update: {
          country?: string | null
          created_at?: string
          email?: string | null
          first_search_id?: string | null
          first_seen_at?: string
          has_website?: boolean
          id?: string
          is_sent?: boolean
          kind?: string | null
          last_search_id?: string | null
          last_seen_at?: string
          notes?: string | null
          page_name?: string | null
          page_url?: string | null
          phone?: string
          sent_at?: string | null
          times_found?: number
          updated_at?: string
          website?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "extracted_numbers_first_search_id_fkey"
            columns: ["first_search_id"]
            isOneToOne: false
            referencedRelation: "searches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "extracted_numbers_last_search_id_fkey"
            columns: ["last_search_id"]
            isOneToOne: false
            referencedRelation: "searches"
            referencedColumns: ["id"]
          },
        ]
      }
      health_status: {
        Row: {
          details: Json | null
          last_heartbeat: string | null
          service: string
          status: string
          updated_at: string
        }
        Insert: {
          details?: Json | null
          last_heartbeat?: string | null
          service: string
          status?: string
          updated_at?: string
        }
        Update: {
          details?: Json | null
          last_heartbeat?: string | null
          service?: string
          status?: string
          updated_at?: string
        }
        Relationships: []
      }
      job_logs: {
        Row: {
          created_at: string
          id: number
          level: string
          message: string
          meta: Json | null
          search_id: string | null
        }
        Insert: {
          created_at?: string
          id?: number
          level?: string
          message: string
          meta?: Json | null
          search_id?: string | null
        }
        Update: {
          created_at?: string
          id?: number
          level?: string
          message?: string
          meta?: Json | null
          search_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "job_logs_search_id_fkey"
            columns: ["search_id"]
            isOneToOne: false
            referencedRelation: "searches"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          created_at: string
          display_name: string | null
          email: string
          id: string
        }
        Insert: {
          created_at?: string
          display_name?: string | null
          email: string
          id: string
        }
        Update: {
          created_at?: string
          display_name?: string | null
          email?: string
          id?: string
        }
        Relationships: []
      }
      search_numbers: {
        Row: {
          created_at: string
          is_new_at_time: boolean
          number_id: string
          search_id: string
        }
        Insert: {
          created_at?: string
          is_new_at_time?: boolean
          number_id: string
          search_id: string
        }
        Update: {
          created_at?: string
          is_new_at_time?: boolean
          number_id?: string
          search_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "search_numbers_number_id_fkey"
            columns: ["number_id"]
            isOneToOne: false
            referencedRelation: "extracted_numbers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "search_numbers_search_id_fkey"
            columns: ["search_id"]
            isOneToOne: false
            referencedRelation: "searches"
            referencedColumns: ["id"]
          },
        ]
      }
      search_pages: {
        Row: {
          created_at: string
          error: string | null
          id: string
          numbers_extracted: number
          page_name: string | null
          page_url: string
          search_id: string
          status: string
        }
        Insert: {
          created_at?: string
          error?: string | null
          id?: string
          numbers_extracted?: number
          page_name?: string | null
          page_url: string
          search_id: string
          status?: string
        }
        Update: {
          created_at?: string
          error?: string | null
          id?: string
          numbers_extracted?: number
          page_name?: string | null
          page_url?: string
          search_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "search_pages_search_id_fkey"
            columns: ["search_id"]
            isOneToOne: false
            referencedRelation: "searches"
            referencedColumns: ["id"]
          },
        ]
      }
      searches: {
        Row: {
          ad_type: string | null
          apify_run_id: string | null
          country: string
          created_at: string
          duration_seconds: number | null
          error_message: string | null
          finished_at: string | null
          id: string
          keyword: string
          language: string | null
          max_pages: number | null
          numbers_found: number
          numbers_new: number
          pages_found: number
          progress: number
          progress_message: string | null
          source: string
          started_at: string | null
          status: Database["public"]["Enums"]["search_status"]
          telegram_chat_id: number | null
          telegram_user_id: number | null
          updated_at: string
          user_id: string | null
        }
        Insert: {
          ad_type?: string | null
          apify_run_id?: string | null
          country: string
          created_at?: string
          duration_seconds?: number | null
          error_message?: string | null
          finished_at?: string | null
          id?: string
          keyword: string
          language?: string | null
          max_pages?: number | null
          numbers_found?: number
          numbers_new?: number
          pages_found?: number
          progress?: number
          progress_message?: string | null
          source?: string
          started_at?: string | null
          status?: Database["public"]["Enums"]["search_status"]
          telegram_chat_id?: number | null
          telegram_user_id?: number | null
          updated_at?: string
          user_id?: string | null
        }
        Update: {
          ad_type?: string | null
          apify_run_id?: string | null
          country?: string
          created_at?: string
          duration_seconds?: number | null
          error_message?: string | null
          finished_at?: string | null
          id?: string
          keyword?: string
          language?: string | null
          max_pages?: number | null
          numbers_found?: number
          numbers_new?: number
          pages_found?: number
          progress?: number
          progress_message?: string | null
          source?: string
          started_at?: string | null
          status?: Database["public"]["Enums"]["search_status"]
          telegram_chat_id?: number | null
          telegram_user_id?: number | null
          updated_at?: string
          user_id?: string | null
        }
        Relationships: []
      }
      user_roles: {
        Row: {
          created_at: string
          id: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          role?: Database["public"]["Enums"]["app_role"]
          user_id?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      get_valid_validation: {
        Args: {
          _contact_type: string
          _contact_value: string
          _validator: string
        }
        Returns: {
          attempts: number
          checked_at: string | null
          contact_type: string
          contact_value: string
          created_at: string
          error_message: string | null
          expires_at: string | null
          id: string
          result: Json
          source_search_id: string | null
          status: string
          updated_at: string
          validator: string
        }
        SetofOptions: {
          from: "*"
          to: "contact_validations"
          isOneToOne: true
          isSetofReturn: false
        }
      }
      has_role: {
        Args: {
          _role: Database["public"]["Enums"]["app_role"]
          _user_id: string
        }
        Returns: boolean
      }
      watchdog_stuck_searches: { Args: never; Returns: undefined }
    }
    Enums: {
      app_role: "admin" | "user"
      key_status: "active" | "exhausted" | "disabled" | "error"
      search_status:
        | "pending"
        | "running"
        | "completed"
        | "failed"
        | "cancelled"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      app_role: ["admin", "user"],
      key_status: ["active", "exhausted", "disabled", "error"],
      search_status: ["pending", "running", "completed", "failed", "cancelled"],
    },
  },
} as const
