import { Alert, Button, Card, Input } from "antd";
import { type FormEvent, useState } from "react";

import { api, userFacingError } from "../../api/client";
import type { Book } from "../../api/types";
import styles from "../ManagedForms.module.css";

interface CreateBookFormProps {
  onCreated: (book: Book) => void | Promise<void>;
}

export function CreateBookForm({ onCreated }: CreateBookFormProps) {
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const book = await api.createBook({
        canonical_title: title,
        canonical_author: author.trim() || null,
        description: description.trim() || null,
      });
      setTitle("");
      setAuthor("");
      setDescription("");
      await onCreated(book);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className={styles.card} title={<h2 className={styles.title}>创建 Book</h2>}>
      <form className={styles.form} onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
        <label className={styles.field} htmlFor="legacy-book-title">
          书名
          <Input
            id="legacy-book-title"
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="例如：银河铁道之夜"
          />
        </label>
        <label className={styles.field} htmlFor="legacy-book-author">
          作者（可选）
          <Input id="legacy-book-author" value={author} onChange={(event) => setAuthor(event.target.value)} />
        </label>
        <label className={styles.field} htmlFor="legacy-book-description">
          简介（可选）
          <Input.TextArea id="legacy-book-description" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        {error ? <Alert type="error" showIcon title={error} /> : null}
        <Button type="primary" htmlType="submit" loading={isSubmitting}>创建作品</Button>
      </form>
    </Card>
  );
}
