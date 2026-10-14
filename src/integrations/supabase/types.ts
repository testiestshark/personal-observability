export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[];

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5";
  };
  public: {
    Tables: {
      daily_health_metrics: {
        Row: {
          active_calories_kcal: number | null;
          calorie_goal_kcal: number | null;
          consumed_calories_kcal: number | null;
          created_at: string;
          day: string;
          external_id: string | null;
          id: string;
          provider: string;
          resting_heart_rate_bpm: number | null;
          sleep_end_at: string | null;
          sleep_start_at: string | null;
          source: string;
          source_synced_at: string | null;
          steps: number | null;
          synced_at: string;
          total_calories_kcal: number | null;
          total_sleep_seconds: number | null;
          user_id: string;
          vo2_max: number | null;
        };
        Insert: {
          active_calories_kcal?: number | null;
          calorie_goal_kcal?: number | null;
          consumed_calories_kcal?: number | null;
          created_at?: string;
          day: string;
          external_id?: string | null;
          id?: string;
          provider: string;
          resting_heart_rate_bpm?: number | null;
          sleep_end_at?: string | null;
          sleep_start_at?: string | null;
          source: string;
          source_synced_at?: string | null;
          steps?: number | null;
          synced_at?: string;
          total_calories_kcal?: number | null;
          total_sleep_seconds?: number | null;
          user_id: string;
          vo2_max?: number | null;
        };
        Update: {
          active_calories_kcal?: number | null;
          calorie_goal_kcal?: number | null;
          consumed_calories_kcal?: number | null;
          created_at?: string;
          day?: string;
          external_id?: string | null;
          id?: string;
          provider?: string;
          resting_heart_rate_bpm?: number | null;
          sleep_end_at?: string | null;
          sleep_start_at?: string | null;
          source?: string;
          source_synced_at?: string | null;
          steps?: number | null;
          synced_at?: string;
          total_calories_kcal?: number | null;
          total_sleep_seconds?: number | null;
          user_id?: string;
          vo2_max?: number | null;
        };
        Relationships: [];
      };
      fitness_activities: {
        Row: {
          active_sets: number | null;
          activity_name: string | null;
          activity_type: string;
          aerobic_training_effect: number | null;
          anaerobic_training_effect: number | null;
          average_cadence_spm: number | null;
          average_heart_rate_bpm: number | null;
          average_power_watts: number | null;
          average_speed_mps: number | null;
          calories_kcal: number | null;
          created_at: string;
          distance_meters: number | null;
          duration_seconds: number | null;
          elapsed_duration_seconds: number | null;
          elevation_gain_meters: number | null;
          elevation_loss_meters: number | null;
          external_id: string;
          id: string;
          local_day: string;
          maximum_cadence_spm: number | null;
          maximum_heart_rate_bpm: number | null;
          maximum_power_watts: number | null;
          maximum_speed_mps: number | null;
          moving_duration_seconds: number | null;
          normalized_power_watts: number | null;
          provider: string;
          source: string;
          started_at: string;
          synced_at: string;
          total_reps: number | null;
          total_sets: number | null;
          total_volume_kg: number | null;
          training_effect_label: string | null;
          training_load: number | null;
          user_id: string;
        };
        Insert: {
          active_sets?: number | null;
          activity_name?: string | null;
          activity_type: string;
          aerobic_training_effect?: number | null;
          anaerobic_training_effect?: number | null;
          average_cadence_spm?: number | null;
          average_heart_rate_bpm?: number | null;
          average_power_watts?: number | null;
          average_speed_mps?: number | null;
          calories_kcal?: number | null;
          created_at?: string;
          distance_meters?: number | null;
          duration_seconds?: number | null;
          elapsed_duration_seconds?: number | null;
          elevation_gain_meters?: number | null;
          elevation_loss_meters?: number | null;
          external_id: string;
          id?: string;
          local_day: string;
          maximum_cadence_spm?: number | null;
          maximum_heart_rate_bpm?: number | null;
          maximum_power_watts?: number | null;
          maximum_speed_mps?: number | null;
          moving_duration_seconds?: number | null;
          normalized_power_watts?: number | null;
          provider: string;
          source: string;
          started_at: string;
          synced_at?: string;
          total_reps?: number | null;
          total_sets?: number | null;
          total_volume_kg?: number | null;
          training_effect_label?: string | null;
          training_load?: number | null;
          user_id: string;
        };
        Update: {
          active_sets?: number | null;
          activity_name?: string | null;
          activity_type?: string;
          aerobic_training_effect?: number | null;
          anaerobic_training_effect?: number | null;
          average_cadence_spm?: number | null;
          average_heart_rate_bpm?: number | null;
          average_power_watts?: number | null;
          average_speed_mps?: number | null;
          calories_kcal?: number | null;
          created_at?: string;
          distance_meters?: number | null;
          duration_seconds?: number | null;
          elapsed_duration_seconds?: number | null;
          elevation_gain_meters?: number | null;
          elevation_loss_meters?: number | null;
          external_id?: string;
          id?: string;
          local_day?: string;
          maximum_cadence_spm?: number | null;
          maximum_heart_rate_bpm?: number | null;
          maximum_power_watts?: number | null;
          maximum_speed_mps?: number | null;
          moving_duration_seconds?: number | null;
          normalized_power_watts?: number | null;
          provider?: string;
          source?: string;
          started_at?: string;
          synced_at?: string;
          total_reps?: number | null;
          total_sets?: number | null;
          total_volume_kg?: number | null;
          training_effect_label?: string | null;
          training_load?: number | null;
          user_id?: string;
        };
        Relationships: [];
      };
      fitness_activity_laps: {
        Row: {
          average_heart_rate_bpm: number | null;
          created_at: string;
          distance_meters: number | null;
          duration_seconds: number;
          elevation_gain_meters: number | null;
          elevation_loss_meters: number | null;
          fitness_activity_id: string;
          id: string;
          position: number;
          user_id: string;
        };
        Insert: {
          average_heart_rate_bpm?: number | null;
          created_at?: string;
          distance_meters?: number | null;
          duration_seconds: number;
          elevation_gain_meters?: number | null;
          elevation_loss_meters?: number | null;
          fitness_activity_id: string;
          id?: string;
          position: number;
          user_id?: string;
        };
        Update: {
          average_heart_rate_bpm?: number | null;
          created_at?: string;
          distance_meters?: number | null;
          duration_seconds?: number;
          elevation_gain_meters?: number | null;
          elevation_loss_meters?: number | null;
          fitness_activity_id?: string;
          id?: string;
          position?: number;
          user_id?: string;
        };
        Relationships: [
          {
            foreignKeyName: "fitness_activity_laps_fitness_activity_id_fkey";
            columns: ["fitness_activity_id"];
            isOneToOne: false;
            referencedRelation: "fitness_activities";
            referencedColumns: ["id"];
          },
        ];
      };
      fitness_exercises: {
        Row: {
          created_at: string;
          exercise_template_id: string | null;
          fitness_activity_id: string;
          id: string;
          notes: string | null;
          position: number;
          superset_id: number | null;
          title: string | null;
          user_id: string;
        };
        Insert: {
          created_at?: string;
          exercise_template_id?: string | null;
          fitness_activity_id: string;
          id?: string;
          notes?: string | null;
          position: number;
          superset_id?: number | null;
          title?: string | null;
          user_id?: string;
        };
        Update: {
          created_at?: string;
          exercise_template_id?: string | null;
          fitness_activity_id?: string;
          id?: string;
          notes?: string | null;
          position?: number;
          superset_id?: number | null;
          title?: string | null;
          user_id?: string;
        };
        Relationships: [
          {
            foreignKeyName: "fitness_exercises_fitness_activity_id_fkey";
            columns: ["fitness_activity_id"];
            isOneToOne: false;
            referencedRelation: "fitness_activities";
            referencedColumns: ["id"];
          },
        ];
      };
      fitness_sets: {
        Row: {
          created_at: string;
          custom_metric: number | null;
          distance_meters: number | null;
          duration_seconds: number | null;
          fitness_exercise_id: string;
          id: string;
          position: number;
          reps: number | null;
          rpe: number | null;
          type: string;
          user_id: string;
          weight_kg: number | null;
        };
        Insert: {
          created_at?: string;
          custom_metric?: number | null;
          distance_meters?: number | null;
          duration_seconds?: number | null;
          fitness_exercise_id: string;
          id?: string;
          position: number;
          reps?: number | null;
          rpe?: number | null;
          type: string;
          user_id?: string;
          weight_kg?: number | null;
        };
        Update: {
          created_at?: string;
          custom_metric?: number | null;
          distance_meters?: number | null;
          duration_seconds?: number | null;
          fitness_exercise_id?: string;
          id?: string;
          position?: number;
          reps?: number | null;
          rpe?: number | null;
          type?: string;
          user_id?: string;
          weight_kg?: number | null;
        };
        Relationships: [
          {
            foreignKeyName: "fitness_sets_fitness_exercise_id_fkey";
            columns: ["fitness_exercise_id"];
            isOneToOne: false;
            referencedRelation: "fitness_exercises";
            referencedColumns: ["id"];
          },
        ];
      };
      github_accounts: {
        Row: {
          created_at: string;
          detail: string;
          display_order: number;
          github_node_id: string;
          github_user_id: number;
          id: string;
          label: string;
          last_synced_at: string | null;
          login: string;
          token_expires_at: string | null;
          user_id: string;
        };
        Insert: {
          created_at?: string;
          detail?: string;
          display_order?: number;
          github_node_id: string;
          github_user_id: number;
          id?: string;
          label: string;
          last_synced_at?: string | null;
          login: string;
          token_expires_at?: string | null;
          user_id?: string;
        };
        Update: {
          created_at?: string;
          detail?: string;
          display_order?: number;
          github_node_id?: string;
          github_user_id?: number;
          id?: string;
          label?: string;
          last_synced_at?: string | null;
          login?: string;
          token_expires_at?: string | null;
          user_id?: string;
        };
        Relationships: [];
      };
      github_commits: {
        Row: {
          account_id: string;
          author_date_raw: string | null;
          authored_at: string;
          id: string;
          local_day: string;
          message_headline: string;
          oid: string;
          repo_is_private: boolean;
          repo_name_with_owner: string;
          repo_node_id: string;
          synced_at: string;
          user_id: string;
        };
        Insert: {
          account_id: string;
          author_date_raw?: string | null;
          authored_at: string;
          id?: string;
          local_day: string;
          message_headline: string;
          oid: string;
          repo_is_private: boolean;
          repo_name_with_owner: string;
          repo_node_id: string;
          synced_at?: string;
          user_id?: string;
        };
        Update: {
          account_id?: string;
          author_date_raw?: string | null;
          authored_at?: string;
          id?: string;
          local_day?: string;
          message_headline?: string;
          oid?: string;
          repo_is_private?: boolean;
          repo_name_with_owner?: string;
          repo_node_id?: string;
          synced_at?: string;
          user_id?: string;
        };
        Relationships: [];
      };
      github_daily_contributions: {
        Row: {
          account_id: string;
          count: number;
          id: string;
          kind: string;
          local_day: string;
          synced_at: string;
          user_id: string;
        };
        Insert: {
          account_id: string;
          count: number;
          id?: string;
          kind: string;
          local_day: string;
          synced_at?: string;
          user_id?: string;
        };
        Update: {
          account_id?: string;
          count?: number;
          id?: string;
          kind?: string;
          local_day?: string;
          synced_at?: string;
          user_id?: string;
        };
        Relationships: [];
      };
      sync_runs: {
        Row: {
          last_succeeded_at: string;
          source: string;
          user_id: string;
        };
        Insert: {
          last_succeeded_at: string;
          source: string;
          user_id: string;
        };
        Update: {
          last_succeeded_at?: string;
          source?: string;
          user_id?: string;
        };
        Relationships: [];
      };
      weight_entries: {
        Row: {
          created_at: string;
          entered_unit: string;
          id: string;
          recorded_at: string;
          user_id: string;
          weight_kg: number;
        };
        Insert: {
          created_at?: string;
          entered_unit: string;
          id?: string;
          recorded_at?: string;
          user_id: string;
          weight_kg: number;
        };
        Update: {
          created_at?: string;
          entered_unit?: string;
          id?: string;
          recorded_at?: string;
          user_id?: string;
          weight_kg?: number;
        };
        Relationships: [];
      };
    };
    Views: {
      [_ in never]: never;
    };
    Functions: {
      replace_fitness_activity_laps: {
        Args: { p_external_id: string; p_laps: Json; p_source: string };
        Returns: number;
      };
      replace_fitness_workout: { Args: { payload: Json }; Returns: string };
    };
    Enums: {
      [_ in never]: never;
    };
    CompositeTypes: {
      [_ in never]: never;
    };
  };
};

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">;

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">];

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals;
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals;
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R;
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] & DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R;
      }
      ? R
      : never
    : never;

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    keyof DefaultSchema["Tables"] | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals;
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals;
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I;
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I;
      }
      ? I
      : never
    : never;

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    keyof DefaultSchema["Tables"] | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals;
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals;
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U;
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U;
      }
      ? U
      : never
    : never;

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    keyof DefaultSchema["Enums"] | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals;
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals;
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never;

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    keyof DefaultSchema["CompositeTypes"] | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals;
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals;
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never;

export const Constants = {
  public: {
    Enums: {},
  },
} as const;
